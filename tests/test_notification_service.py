from datetime import datetime
from uuid import UUID, uuid4

import pytest

from src.models import IntervalResultDB, MonitoringJobDB, interval_time
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


TIMESTAMP = "2026-10-29T10:00:00+00:00"


def add_interval(session_factory, job_id, notified=False):
    with session_factory() as db:
        db.add(IntervalResultDB(
            job_id=UUID(job_id),
            timestamp=interval_time(TIMESTAMP),
            avg_sentiment=1.8,
            avg_confidence=0.9,
            notified_at=datetime(2026, 10, 29, 10, 1) if notified else None,
        ))
        db.commit()


def notify(session_factory, job_id, send):
    handle_notification(
        {"job_id": job_id, "interval_timestamp": TIMESTAMP, "aggregate": AGGREGATE},
        session_factory=session_factory,
        send=send,
        from_email="bot@example.com",
    )


def notified_at(session_factory, job_id):
    with session_factory() as db:
        return db.query(IntervalResultDB).filter_by(job_id=UUID(job_id)).one().notified_at


def test_handler_emails_the_jobs_owner(session_factory, job):
    add_interval(session_factory, job["job_id"])
    sent = []
    notify(session_factory, job["job_id"], sent.append)

    [msg] = sent
    assert msg["To"] == "ada@example.com"
    assert msg["From"] == "bot@example.com"
    assert "My video" in msg["Subject"]
    html = msg.get_payload()[0].get_payload(decode=True).decode()
    assert "Hi Ada Lovelace" in html
    assert "Positive" in html and "Negative" in html  # interval vs overall
    assert "4.0 hours" in html
    assert notified_at(session_factory, job["job_id"]) is not None


def test_untrusted_title_and_name_are_html_escaped(session_factory, job):
    hostile = '<a href="https://evil.example">Verify your account</a>'
    with session_factory() as db:
        row = db.get(MonitoringJobDB, UUID(job["job_id"]))
        row.post_title = hostile
        row.user_full_name = "<script>alert(1)</script>"
        db.commit()
    add_interval(session_factory, job["job_id"])
    sent = []
    notify(session_factory, job["job_id"], sent.append)

    html = sent[0].get_payload()[0].get_payload(decode=True).decode()
    assert hostile not in html and "<script>" not in html
    assert "&lt;a href=" in html and "&lt;script&gt;" in html


def test_redelivered_notification_sends_one_email(session_factory, job):
    add_interval(session_factory, job["job_id"])
    sent = []
    notify(session_factory, job["job_id"], sent.append)
    notify(session_factory, job["job_id"], sent.append)
    assert len(sent) == 1


def test_already_notified_interval_is_skipped(session_factory, job):
    add_interval(session_factory, job["job_id"], notified=True)
    sent = []
    notify(session_factory, job["job_id"], sent.append)
    assert sent == []


def test_failed_send_leaves_the_interval_unnotified_for_retry(session_factory, job):
    add_interval(session_factory, job["job_id"])

    def broken_smtp(msg):
        raise ConnectionError("SMTP down")

    with pytest.raises(ConnectionError):
        notify(session_factory, job["job_id"], broken_smtp)
    assert notified_at(session_factory, job["job_id"]) is None

    sent = []
    notify(session_factory, job["job_id"], sent.append)  # the retry
    assert len(sent) == 1


def test_handler_fails_for_an_unknown_job(session_factory):
    with pytest.raises(ValueError, match="not found"):
        notify(session_factory, str(uuid4()), lambda msg: None)


def test_handler_fails_when_the_interval_is_missing(session_factory, job):
    with pytest.raises(ValueError, match="interval"):
        notify(session_factory, job["job_id"], lambda msg: None)
