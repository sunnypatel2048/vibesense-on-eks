"""Ingestion worker: fetches a job's new YouTube comments each interval.

Reads:  ingest queue    {job_id, post_id}   (from EventBridge Scheduler, or the
                                            local scheduler in development)
Writes: analysis queue  {job_id, interval_timestamp, comments: [str, ...]}

Run with: python -m src.ingestion_service.app
"""
from datetime import datetime, timezone
from functools import partial
from typing import Any, Callable
from uuid import UUID

import structlog
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.common.config import IngestionSettings, get_settings
from src.common.queue import consume, publish
from src.common.scheduler import as_utc, job_end
from src.ingestion_service.preprocessor import preprocess_text
from src.ingestion_service.youtube_fetcher import fetch_comments, parse_published_at
from src.models import MonitoringJobDB

logger = structlog.get_logger()

Fetcher = Callable[[str, datetime | None], list[dict[str, Any]]]
Cleaner = Callable[[str], str]
Publisher = Callable[[str, dict[str, Any]], Any]
SessionFactory = Callable[[], Session]


def handle_ingest(
    payload: dict[str, Any],
    *,
    session_factory: SessionFactory,
    fetch: Fetcher,
    clean: Cleaner,
    publish_to: Publisher,
    next_queue: str,
    now: datetime | None = None,
) -> None:
    now = now or datetime.now(timezone.utc)
    job_id = payload["job_id"]
    log = logger.bind(job_id=job_id)

    with session_factory() as db:
        job = db.get(MonitoringJobDB, UUID(job_id))
        if job is None:
            log.warning("job_not_found")  # deleted; nothing to retry
            return
        if now >= job_end(job):
            log.info("job_expired")  # its schedule ends on its own
            return

        since = as_utc(job.last_fetched_at) if job.last_fetched_at else None
        new_comments = [
            c
            for c in fetch(job.post_id, since)
            if since is None or parse_published_at(c["published_at"]) > since
        ]
        if not new_comments:
            log.info("no_new_comments")
            return

        newest = max(new_comments, key=lambda c: parse_published_at(c["published_at"]))
        # Publish first, then record progress. If the save fails, the retry
        # republishes the same batch with the same interval_timestamp, which
        # aggregation de-duplicates (Task 1.6). The reverse order could lose comments.
        publish_to(
            next_queue,
            {
                "job_id": job_id,
                "interval_timestamp": newest["published_at"],
                "comments": [clean(c["text"]) for c in new_comments],
            },
        )
        job.last_fetched_at = parse_published_at(newest["published_at"]).astimezone(timezone.utc).replace(tzinfo=None)
        db.commit()

    log.info("comments_ingested", count=len(new_comments))


def main() -> None:
    settings = get_settings(IngestionSettings)
    engine = create_engine(settings.db_url.get_secret_value(), pool_pre_ping=True)
    handler = partial(
        handle_ingest,
        session_factory=sessionmaker(bind=engine),
        fetch=fetch_comments,
        clean=preprocess_text,
        publish_to=publish,
        next_queue=settings.analysis_queue,
    )
    # One job at a time: a busy video can take many API pages to fetch.
    consume(settings.ingest_queue, handler, batch_size=1)


if __name__ == "__main__":
    main()
