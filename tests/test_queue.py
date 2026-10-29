import json
from datetime import datetime, timezone
from types import SimpleNamespace

import boto3
import pytest
from moto import mock_aws

from src.common import queue
from src.common.config import get_settings
from src.common.queue import MAX_MESSAGE_BYTES, Consumer, PayloadTooLargeError, publish

QUEUE = "test-queue"


@pytest.fixture
def sqs(monkeypatch, tmp_path):
    """An in-memory SQS (moto) with one queue whose DLQ takes over after 2 receives."""
    monkeypatch.chdir(tmp_path)  # keep the project's .env out of these tests
    for name, value in {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "AWS_REGION": "us-east-1",
        "AWS_DEFAULT_REGION": "us-east-1",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("SQS_ENDPOINT_URL", raising=False)
    get_settings.cache_clear()
    queue.reset_caches()

    with mock_aws():
        client = boto3.client("sqs", region_name="us-east-1")
        dlq_url = client.create_queue(QueueName=f"{QUEUE}-dlq")["QueueUrl"]
        dlq_arn = client.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["QueueArn"])[
            "Attributes"
        ]["QueueArn"]
        url = client.create_queue(
            QueueName=QUEUE,
            Attributes={
                "VisibilityTimeout": "30",
                "RedrivePolicy": json.dumps(
                    {"deadLetterTargetArn": dlq_arn, "maxReceiveCount": "2"}
                ),
            },
        )["QueueUrl"]
        yield SimpleNamespace(client=client, url=url, dlq_url=dlq_url)

    get_settings.cache_clear()
    queue.reset_caches()


def counts(client, url):
    """(visible, in flight) message counts for a queue."""
    attrs = client.get_queue_attributes(
        QueueUrl=url,
        AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"],
    )["Attributes"]
    return (
        int(attrs["ApproximateNumberOfMessages"]),
        int(attrs["ApproximateNumberOfMessagesNotVisible"]),
    )


def run_once(handler, **options):
    consumer = Consumer(QUEUE, handler, wait_seconds=0, **options)
    consumer.run(max_polls=1, install_signal_handlers=False)
    return consumer


def test_published_message_reaches_handler_and_is_deleted(sqs):
    sent_at = datetime(2026, 10, 29, tzinfo=timezone.utc)
    publish(QUEUE, {"job_id": "abc", "sent_at": sent_at})

    received = []
    run_once(received.append)

    assert received == [{"job_id": "abc", "sent_at": str(sent_at)}]
    assert counts(sqs.client, sqs.url) == (0, 0)


def test_failed_message_is_kept_and_hidden_for_the_backoff_delay(sqs):
    publish(QUEUE, {"job_id": "abc"})

    def fail(_payload):
        raise RuntimeError("downstream unavailable")

    run_once(fail, retry_delays_seconds=(60,))

    assert counts(sqs.client, sqs.url) == (0, 1)  # not deleted, hidden for retry


def test_repeatedly_failing_message_ends_up_in_the_dlq(sqs):
    publish(QUEUE, {"job_id": "poison"})

    def fail(_payload):
        raise ValueError("cannot process")

    consumer = Consumer(QUEUE, fail, wait_seconds=0, retry_delays_seconds=(0,))
    consumer.run(max_polls=5, install_signal_handlers=False)

    assert counts(sqs.client, sqs.url) == (0, 0)
    assert counts(sqs.client, sqs.dlq_url)[0] == 1


def test_malformed_json_is_never_passed_to_the_handler(sqs):
    sqs.client.send_message(QueueUrl=sqs.url, MessageBody="not json")
    received = []

    run_once(received.append, retry_delays_seconds=(60,))

    assert received == []
    assert counts(sqs.client, sqs.url) == (0, 1)


def test_oversized_payload_is_rejected_before_sending(sqs):
    with pytest.raises(PayloadTooLargeError):
        publish(QUEUE, {"blob": "x" * MAX_MESSAGE_BYTES})
    assert counts(sqs.client, sqs.url) == (0, 0)


def test_stop_releases_messages_that_were_not_started(sqs):
    for n in range(3):
        publish(QUEUE, {"n": n})

    handled = []
    consumer = Consumer(QUEUE, lambda p: None, wait_seconds=0)

    def handle_then_stop(payload):
        handled.append(payload)
        consumer.stop()  # simulate SIGTERM arriving mid-batch

    consumer.handler = handle_then_stop
    consumer.run(max_polls=1, install_signal_handlers=False)

    assert len(handled) == 1
    remaining = sqs.client.receive_message(QueueUrl=sqs.url, MaxNumberOfMessages=10)
    assert len(remaining.get("Messages", [])) == 2  # visible again immediately


def test_poll_updates_last_poll(sqs):
    consumer = Consumer(QUEUE, lambda p: None, wait_seconds=0)
    before = consumer.last_poll
    consumer.poll_once()
    assert consumer.last_poll > before


@pytest.mark.parametrize("batch_size", [0, 11])
def test_batch_size_must_be_between_1_and_10(batch_size):
    with pytest.raises(ValueError):
        Consumer(QUEUE, lambda p: None, batch_size=batch_size)


# --- Metrics and health state (Task 1.8) ---------------------------------------

from prometheus_client import REGISTRY  # noqa: E402


def metric(name, **labels):
    return REGISTRY.get_sample_value(name, labels) or 0.0


def test_success_and_failure_are_counted(sqs):
    ok_before = metric("vibesense_messages_total", queue=QUEUE, result="success")
    fail_before = metric("vibesense_messages_total", queue=QUEUE, result="failure")
    published_before = metric("vibesense_messages_published_total", queue=QUEUE)

    publish(QUEUE, {"ok": True})
    publish(QUEUE, {"ok": False})

    def handler(payload):
        if not payload["ok"]:
            raise ValueError("bad")

    run_once(handler, retry_delays_seconds=(60,))

    assert metric("vibesense_messages_total", queue=QUEUE, result="success") == ok_before + 1
    assert metric("vibesense_messages_total", queue=QUEUE, result="failure") == fail_before + 1
    assert metric("vibesense_messages_published_total", queue=QUEUE) == published_before + 2
    assert metric("vibesense_last_success_timestamp_seconds", queue=QUEUE) > 0


def test_consumer_is_busy_only_while_handling(sqs):
    publish(QUEUE, {"n": 1})
    seen = []
    consumer = Consumer(QUEUE, lambda p: None, wait_seconds=0)
    consumer.handler = lambda payload: seen.append(consumer.busy_since)

    assert not consumer.has_polled
    consumer.run(max_polls=1, install_signal_handlers=False)

    assert seen[0] is not None  # busy while the handler ran
    assert consumer.busy_since is None  # idle afterwards
    assert consumer.has_polled
