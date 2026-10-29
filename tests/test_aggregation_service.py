import pytest

from src.aggregation_service.app import aggregate_interval, handle_aggregation
from src.models import AnalysisOutput


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
