from uuid import UUID

import pytest

from src.aggregation_service.app import aggregate_interval, handle_aggregation
from src.models import AnalysisOutput, IntervalResultDB


def result(sentiment, confidence):
    return AnalysisOutput(text="", sentiment=sentiment, confidence=confidence)


def test_interval_score_is_confidence_weighted():
    sentiment, confidence = aggregate_interval([result("Positive", 0.9), result("Negative", 0.1)])
    # (2 * 0.9 + 0 * 0.1) / (0.9 + 0.1)
    assert sentiment == pytest.approx(1.8)
    assert confidence == pytest.approx(0.5)


def test_unknown_label_is_rejected():
    with pytest.raises(ValueError, match="unknown sentiment"):
        aggregate_interval([result("Ecstatic", 0.9)])


def test_empty_interval_is_rejected():
    with pytest.raises(ValueError):
        aggregate_interval([])


def payload(job_id, timestamp, *results):
    return {
        "job_id": job_id,
        "interval_timestamp": timestamp,
        "results": [r.model_dump() for r in results],
    }


def test_handler_stores_interval_and_publishes_running_overall(session_factory, job, published):
    deps = dict(session_factory=session_factory, publish_to=published, next_queue="notify")

    handle_aggregation(
        payload(job["job_id"], "2026-10-29T10:00:00+00:00", result("Positive", 0.9), result("Negative", 0.1)),
        **deps,
    )
    handle_aggregation(payload(job["job_id"], "2026-10-29T14:00:00+00:00", result("Neutral", 1.0)), **deps)

    assert [queue for queue, _ in published.calls] == ["notify", "notify"]
    latest = published.calls[-1][1]
    assert latest["job_id"] == job["job_id"]
    assert latest["aggregate"]["interval_sentiment"] == pytest.approx(1.0)
    assert latest["aggregate"]["overall_sentiment"] == pytest.approx((1.8 + 1.0) / 2)
    assert latest["aggregate"]["overall_confidence"] == pytest.approx((0.5 + 1.0) / 2)
    assert "results" not in latest


def interval_rows(session_factory, job_id):
    with session_factory() as db:
        return db.query(IntervalResultDB).filter_by(job_id=UUID(job_id)).count()


def test_redelivered_message_stores_one_row_but_still_publishes(session_factory, job, published):
    message = payload(job["job_id"], "2026-10-29T10:00:00Z", result("Positive", 0.9))
    deps = dict(session_factory=session_factory, publish_to=published, next_queue="notify")

    handle_aggregation(message, **deps)
    handle_aggregation(message, **deps)

    assert interval_rows(session_factory, job["job_id"]) == 1
    assert len(published.calls) == 2  # notification de-duplicates the email
    assert published.calls[1][1]["aggregate"]["overall_sentiment"] == pytest.approx(2.0)  # average not skewed


def test_retry_after_a_failed_publish_still_reaches_notification(session_factory, job, published):
    message = payload(job["job_id"], "2026-10-29T10:00:00Z", result("Neutral", 1.0))

    def broken_publish(queue, body):
        raise ConnectionError("SQS unavailable")

    with pytest.raises(ConnectionError):
        handle_aggregation(message, session_factory=session_factory, publish_to=broken_publish, next_queue="notify")
    handle_aggregation(message, session_factory=session_factory, publish_to=published, next_queue="notify")

    assert interval_rows(session_factory, job["job_id"]) == 1
    assert len(published.calls) == 1
