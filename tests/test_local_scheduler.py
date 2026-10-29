from datetime import datetime, timedelta, timezone
from uuid import UUID

from src.local_scheduler.app import DueJobTracker, next_boundary
from src.models import MonitoringJobDB


def test_next_boundary_is_the_first_boundary_after_now():
    created = datetime(2026, 10, 29, 12, 0)  # naive UTC
    now = datetime(2026, 10, 29, 12, 7, tzinfo=timezone.utc)
    assert next_boundary(created, 300, now) == datetime(2026, 10, 29, 12, 10, tzinfo=timezone.utc)


def test_next_boundary_right_after_creation_is_one_interval_later():
    created = datetime(2026, 10, 29, 12, 0)
    now = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
    assert next_boundary(created, 300, now) == datetime(2026, 10, 29, 12, 5, tzinfo=timezone.utc)


def test_tracker_enqueues_each_job_once_per_interval(session_factory, job, published):
    with session_factory() as db:
        created = db.get(MonitoringJobDB, UUID(job["job_id"])).created_at
    start = created.replace(tzinfo=timezone.utc)
    tracker = DueJobTracker(session_factory, published, "ingest")

    assert tracker.tick(start + timedelta(minutes=1)) == 0           # first sighting
    assert tracker.tick(start + timedelta(hours=3)) == 0             # before the 4 h boundary
    assert tracker.tick(start + timedelta(hours=4, minutes=1)) == 1  # due
    assert tracker.tick(start + timedelta(hours=4, minutes=2)) == 0  # not twice
    assert tracker.tick(start + timedelta(hours=8, minutes=1)) == 1  # next interval

    assert published.calls[0] == ("ingest", {"job_id": job["job_id"], "post_id": "vid123"})


def test_tracker_ignores_expired_jobs(session_factory, job, published):
    tracker = DueJobTracker(session_factory, published, "ingest")
    far_future = datetime.now(timezone.utc) + timedelta(days=30)
    assert tracker.tick(far_future) == 0
    assert tracker.next_due == {}
