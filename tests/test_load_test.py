import random
from datetime import UTC, datetime

from src.load_test import EMAIL_DOMAIN, POST_ID, build_messages, cleanup, create_jobs
from src.models import IntervalResultDB, MonitoringJobDB


def test_create_jobs_makes_suppressed_synthetic_jobs(session_factory):
    with session_factory() as db:
        ids = create_jobs(db, 3)
        rows = db.query(MonitoringJobDB).filter(MonitoringJobDB.job_id.in_(ids)).all()
    assert len(rows) == 3
    assert all(r.post_id == POST_ID and r.email.endswith("@" + EMAIL_DOMAIN) for r in rows)
    assert not any(r.is_scheduled for r in rows)


def test_build_messages_spreads_over_jobs_with_unique_intervals(session_factory):
    with session_factory() as db:
        ids = create_jobs(db, 3)
    start = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
    messages = build_messages(ids, 10, 4, random.Random(1), start)

    assert len(messages) == 10
    assert {m["job_id"] for m in messages} == {str(i) for i in ids}
    assert all(len(m["comments"]) == 4 for m in messages)
    keys = {(m["job_id"], m["interval_timestamp"]) for m in messages}
    assert len(keys) == 10  # each message becomes its own interval row
    assert messages[0]["interval_timestamp"] == "2026-11-15T12:00:00Z"


def test_cleanup_removes_only_synthetic_jobs(session_factory, job):
    with session_factory() as db:
        [load_id] = create_jobs(db, 1)
        db.add(IntervalResultDB(job_id=load_id, timestamp=datetime(2026, 11, 15, 12, 0)))
        db.commit()
        assert cleanup(db) == (1, 1)
        remaining = [str(r.job_id) for r in db.query(MonitoringJobDB)]
    assert remaining == [job["job_id"]]  # the real job is untouched
