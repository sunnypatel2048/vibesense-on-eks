"""Publish JSON messages to SQS and consume them reliably.

How reliability works with SQS:
  * A received message is hidden from other consumers for the queue's
    visibility timeout.
  * On success we delete it. On failure we do nothing except choose when it
    reappears (backoff); SQS redelivers it then.
  * After the queue's maxReceiveCount failed receives, SQS moves it to the
    queue's dead-letter queue (DLQ).

Delivery is at-least-once: a message can be handled twice (for example if a
pod dies after the handler ran but before the delete), so handlers must be
idempotent.
"""
from __future__ import annotations

import json
import signal
import threading
import time
from functools import lru_cache
from typing import Any, Callable, Sequence

import boto3
import structlog
from botocore.config import Config

from src.common.config import QueueSettings, get_settings

logger = structlog.get_logger()

# SQS's per-message limit since August 2025.
MAX_MESSAGE_BYTES = 1024 * 1024

# How long a failed message stays hidden before its next attempt, indexed by
# how many times it has been received (1st failure -> 10 s, 2nd -> 30 s, ...).
DEFAULT_RETRY_DELAYS_SECONDS: tuple[int, ...] = (10, 30, 90, 270)

Handler = Callable[[dict[str, Any]], None]


class PayloadTooLargeError(ValueError):
    """Raised by publish() before sending a message SQS would reject."""


# --- Client and queue lookup -------------------------------------------------

@lru_cache
def _client():
    settings = get_settings(QueueSettings)
    kwargs: dict[str, Any] = {
        "region_name": settings.aws_region,
        "config": Config(retries={"mode": "standard", "max_attempts": 5}),
    }
    if settings.sqs_endpoint_url:
        # Local ElasticMQ ignores signatures, so dummy credentials keep local
        # runs independent of your real AWS login.
        kwargs.update(
            endpoint_url=settings.sqs_endpoint_url,
            aws_access_key_id="local",
            aws_secret_access_key="local",
        )
    return boto3.client("sqs", **kwargs)


@lru_cache
def queue_url(queue_name: str) -> str:
    """Resolve a queue name to its URL once per process."""
    return _client().get_queue_url(QueueName=queue_name)["QueueUrl"]


def reset_caches() -> None:
    """For tests: forget the cached client and queue URLs."""
    _client.cache_clear()
    queue_url.cache_clear()


# --- Publishing --------------------------------------------------------------

def publish(queue_name: str, payload: dict[str, Any]) -> str:
    """Send one JSON message and return its SQS message ID."""
    body = json.dumps(payload, default=str)  # default=str handles datetimes
    size = len(body.encode("utf-8"))
    if size > MAX_MESSAGE_BYTES:
        raise PayloadTooLargeError(
            f"{queue_name}: payload is {size} bytes; the SQS limit is {MAX_MESSAGE_BYTES}"
        )
    response = _client().send_message(QueueUrl=queue_url(queue_name), MessageBody=body)
    logger.debug("message_published", queue=queue_name, message_id=response["MessageId"], bytes=size)
    return response["MessageId"]


# --- Consuming ---------------------------------------------------------------

class Consumer:
    """Long-polls one queue and passes each JSON payload to `handler`.

    `batch_size`: messages per receive (1-10). Use 1 for slow handlers so a
    single pod doesn't hold messages other pods could be working on.
    `last_poll`: monotonic time of the last successful poll; the health check
    (Task 1.8) treats a stale value as a stuck consumer.
    """

    def __init__(
        self,
        queue_name: str,
        handler: Handler,
        *,
        batch_size: int = 10,
        wait_seconds: int = 20,
        retry_delays_seconds: Sequence[int] = DEFAULT_RETRY_DELAYS_SECONDS,
    ) -> None:
        if not 1 <= batch_size <= 10:
            raise ValueError("batch_size must be between 1 and 10")
        if not retry_delays_seconds:
            raise ValueError("retry_delays_seconds must not be empty")
        self.queue_name = queue_name
        self.handler = handler
        self.batch_size = batch_size
        self.wait_seconds = wait_seconds
        self.retry_delays_seconds = tuple(retry_delays_seconds)
        self.last_poll = time.monotonic()
        self._stopping = threading.Event()
        self._log = logger.bind(queue=queue_name)

    def stop(self, *_: Any) -> None:
        """Ask the loop to finish the current message and exit."""
        if not self._stopping.is_set():
            self._log.info("consumer_stopping")
        self._stopping.set()

    @property
    def stopping(self) -> bool:
        return self._stopping.is_set()

    def run(self, *, max_polls: int | None = None, install_signal_handlers: bool = True) -> None:
        """Poll until stopped (SIGTERM/SIGINT) or `max_polls` is reached."""
        if install_signal_handlers and threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, self.stop)
            signal.signal(signal.SIGINT, self.stop)

        url = queue_url(self.queue_name)
        self._log.info("consumer_started", batch_size=self.batch_size)
        polls = 0
        while not self.stopping and (max_polls is None or polls < max_polls):
            polls += 1
            self.poll_once(url)
        self._log.info("consumer_stopped")

    def poll_once(self, url: str | None = None) -> int:
        """Receive one batch and process it. Returns how many messages succeeded."""
        url = url or queue_url(self.queue_name)
        try:
            response = _client().receive_message(
                QueueUrl=url,
                MaxNumberOfMessages=self.batch_size,
                WaitTimeSeconds=self.wait_seconds,
                AttributeNames=["ApproximateReceiveCount"],
            )
        except Exception:
            # Network blip or throttling: keep going; a persistent problem
            # shows up as a stale last_poll and fails the health check.
            self._log.exception("receive_failed")
            self._stopping.wait(2)
            return 0

        self.last_poll = time.monotonic()
        messages = response.get("Messages", [])
        succeeded = 0
        for index, message in enumerate(messages):
            if self.stopping:
                self._release(url, messages[index:])
                break
            succeeded += self._process(url, message)
        return succeeded

    def _process(self, url: str, message: dict[str, Any]) -> bool:
        receive_count = int(message.get("Attributes", {}).get("ApproximateReceiveCount", "1"))
        log = self._log.bind(message_id=message["MessageId"], receive_count=receive_count)
        try:
            payload = json.loads(message["Body"])
            self.handler(payload)
        except Exception:
            log.exception("message_failed")
            self._backoff(url, message, receive_count)
            return False

        try:
            _client().delete_message(QueueUrl=url, ReceiptHandle=message["ReceiptHandle"])
        except Exception:
            # The work is done but the message will reappear; the idempotent
            # handler makes the second delivery harmless.
            log.exception("delete_failed")
            return False
        log.debug("message_processed")
        return True

    def _backoff(self, url: str, message: dict[str, Any], receive_count: int) -> None:
        delays = self.retry_delays_seconds
        delay = delays[min(receive_count, len(delays)) - 1]
        try:
            _client().change_message_visibility(
                QueueUrl=url, ReceiptHandle=message["ReceiptHandle"], VisibilityTimeout=delay
            )
        except Exception:
            # Falls back to the queue's default visibility timeout.
            self._log.exception("backoff_failed", message_id=message["MessageId"])

    def _release(self, url: str, messages: list[dict[str, Any]]) -> None:
        """Make received-but-unstarted messages visible again immediately."""
        entries = [
            {"Id": str(i), "ReceiptHandle": m["ReceiptHandle"], "VisibilityTimeout": 0}
            for i, m in enumerate(messages)
        ]
        try:
            _client().change_message_visibility_batch(QueueUrl=url, Entries=entries)
            self._log.info("messages_released", count=len(entries))
        except Exception:
            self._log.exception("release_failed", count=len(entries))


def consume(queue_name: str, handler: Handler, **options: Any) -> None:
    """Run a consumer for `queue_name` until the process is asked to stop."""
    Consumer(queue_name, handler, **options).run()
