import time
from uuid import uuid4

from src.models import MonitoringJobDB


def test_created_at_default_is_evaluated_per_row(session_factory):
    with session_factory() as db:
        first = MonitoringJobDB(job_id=uuid4(), post_id="a", user_full_name="A", email="a@x.io",
                                intervals_seconds=300, total_duration_seconds=1800)
        db.add(first)
        db.commit()
        time.sleep(0.01)
        second = MonitoringJobDB(job_id=uuid4(), post_id="b", user_full_name="B", email="b@x.io",
                                 intervals_seconds=300, total_duration_seconds=1800)
        db.add(second)
        db.commit()

        assert first.created_at is not None
        assert second.created_at > first.created_at
