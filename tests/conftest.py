from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models import Base, MonitoringJobDB


@pytest.fixture
def session_factory():
    """A throwaway in-memory database with the app's tables."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine)
    engine.dispose()


@pytest.fixture
def job(session_factory):
    """One monitoring job (4-hour interval) already in the database."""
    with session_factory() as db:
        row = MonitoringJobDB(
            job_id=uuid4(),
            post_id="vid123",
            post_title="My video",
            user_full_name="Ada Lovelace",
            email="ada@example.com",
            intervals_seconds=4 * 3600,
            total_duration_seconds=24 * 3600,
            created_at=datetime.now(timezone.utc),
        )
        db.add(row)
        db.commit()
        return {"job_id": str(row.job_id), "post_title": row.post_title}


class Recorder:
    """Stands in for publish(): records (queue, payload) instead of sending."""

    def __init__(self):
        self.calls = []

    def __call__(self, queue, payload):
        self.calls.append((queue, payload))


@pytest.fixture
def published():
    return Recorder()
