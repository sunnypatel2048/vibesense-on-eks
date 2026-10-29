"""Development stand-in for EventBridge Scheduler. Never deployed.

Every POLL_SECONDS it puts {job_id, post_id} on the ingest queue for each
active job whose next interval boundary has passed. Next-due times live in
memory, so a restart doesn't replay missed intervals; it just waits for each
job's next boundary.

Run with: python -m src.local_scheduler.app
"""
import math
import signal
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import structlog
from sqlalchemy.orm import Session

from src.common.config import LocalSchedulerSettings, get_settings
from src.common.db import create_session_factory
from src.common.queue import publish
from src.common.scheduler import as_utc, ingest_message, job_end
from src.common.logs import configure_logging
from src.models import MonitoringJobDB

logger = structlog.get_logger()

POLL_SECONDS = 30

Publisher = Callable[[str, dict[str, Any]], Any]
SessionFactory = Callable[[], Session]


def next_boundary(created_at: datetime, interval_seconds: float, now: datetime) -> datetime:
    """The first interval boundary (created + k * interval, k >= 1) after `now`."""
    elapsed = (now - as_utc(created_at)).total_seconds()
    k = max(1, math.floor(elapsed / interval_seconds) + 1)
    return as_utc(created_at) + timedelta(seconds=k * interval_seconds)


class DueJobTracker:
    def __init__(self, session_factory: SessionFactory, publish_to: Publisher, ingest_queue: str) -> None:
        self.session_factory = session_factory
        self.publish_to = publish_to
        self.ingest_queue = ingest_queue
        self.next_due: dict[str, datetime] = {}

    def tick(self, now: datetime) -> int:
        """Enqueue every job that is due at `now`. Returns how many were enqueued."""
        with self.session_factory() as db:
            jobs = db.query(MonitoringJobDB).all()  # dev data is small

        enqueued = 0
        active = set()
        for job in jobs:
            job_id = str(job.job_id)
            if now >= job_end(job):
                continue
            active.add(job_id)

            due = self.next_due.get(job_id)
            if due is None:
                # First sighting: wait for the next boundary.
                self.next_due[job_id] = next_boundary(job.created_at, job.intervals_seconds, now)
                continue
            if now >= due:
                self.publish_to(self.ingest_queue, ingest_message(job))
                enqueued += 1
                logger.info("job_enqueued", job_id=job_id)
                self.next_due[job_id] = next_boundary(job.created_at, job.intervals_seconds, now)

        # Forget jobs that ended or were deleted.
        for job_id in set(self.next_due) - active:
            del self.next_due[job_id]
        return enqueued


def main() -> None:
    configure_logging("local-scheduler")
    settings = get_settings(LocalSchedulerSettings)
    tracker = DueJobTracker(create_session_factory(settings), publish, settings.ingest_queue)

    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())

    logger.info("local_scheduler_started", poll_seconds=POLL_SECONDS)
    while not stopping.is_set():
        try:
            tracker.tick(datetime.now(timezone.utc))
        except Exception:
            logger.exception("tick_failed")
        stopping.wait(POLL_SECONDS)


if __name__ == "__main__":
    main()
