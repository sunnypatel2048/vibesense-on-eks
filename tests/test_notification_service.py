from uuid import uuid4

import pytest

from src.notification_service.app import confidence_label, handle_notification, sentiment_label

AGGREGATE = {
    "interval_sentiment": 1.8,
    "interval_confidence": 0.9,
    "overall_sentiment": 0.5,
    "overall_confidence": 0.5,
}


@pytest.mark.parametrize(
    "score, label", [(0.0, "Negative"), (0.66, "Negative"), (0.67, "Neutral"), (1.33, "Positive"), (2.0, "Positive")]
)
def test_sentiment_label(score, label):
    assert sentiment_label(score) == label


@pytest.mark.parametrize("confidence, label", [(0.1, "Uncertain"), (0.5, "Moderate"), (0.9, "High")])
def test_confidence_label(confidence, label):
    assert confidence_label(confidence) == label


def test_handler_emails_the_jobs_owner(session_factory, job):
    sent = []
    handle_notification(
        {"job_id": job["job_id"], "interval_timestamp": "2026-10-29T10:00:00+00:00", "aggregate": AGGREGATE},
        session_factory=session_factory,
        send=sent.append,
        from_email="bot@example.com",
    )

    [msg] = sent
    assert msg["To"] == "ada@example.com"
    assert msg["From"] == "bot@example.com"
    assert "My video" in msg["Subject"]
    html = msg.get_payload()[0].get_payload(decode=True).decode()
    assert "Hi Ada Lovelace" in html
    assert "Positive" in html and "Negative" in html  # interval vs overall
    assert "4.0 hours" in html


def test_handler_fails_for_an_unknown_job(session_factory):
    with pytest.raises(ValueError, match="not found"):
        handle_notification(
            {"job_id": str(uuid4()), "interval_timestamp": "2026-10-29T10:00:00+00:00", "aggregate": AGGREGATE},
            session_factory=session_factory,
            send=lambda msg: None,
            from_email="bot@example.com",
        )
