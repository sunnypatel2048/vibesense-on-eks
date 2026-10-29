"""Aggregation worker: turns one interval's scored comments into a sentiment
score, stores it, and recomputes the job's overall average.

Reads:  aggregation queue   {job_id, interval_timestamp, results: [AnalysisOutput, ...]}
Writes: notification queue  {job_id, interval_timestamp, aggregate: Aggregate}

Run with: python -m src.aggregation_service.app
"""
from functools import partial
from typing import Any, Callable, Sequence
from uuid import UUID

import structlog
from sqlalchemy import create_engine, func
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session, sessionmaker

from src.common.config import AggregationSettings, get_settings
from src.common.queue import consume, publish
from src.models import Aggregate, AnalysisOutput, Base, IntervalResultDB, interval_time

logger = structlog.get_logger()

# Model labels mapped onto a 0 (negative) .. 2 (positive) scale.
SENTIMENT_SCORES = {
    "Very Negative": 0,
    "Negative": 0,
    "Neutral": 1,
    "Positive": 2,
    "Very Positive": 2,
}

Publisher = Callable[[str, dict[str, Any]], Any]
SessionFactory = Callable[[], Session]


def aggregate_interval(results: Sequence[AnalysisOutput]) -> tuple[float, float]:
    """Return (confidence-weighted sentiment, mean confidence) for one interval."""
    if not results:
        raise ValueError("no results to aggregate")
    unknown = {r.sentiment for r in results} - SENTIMENT_SCORES.keys()
    if unknown:
        raise ValueError(f"unknown sentiment labels: {sorted(unknown)}")

    total_confidence = sum(r.confidence for r in results)
    if total_confidence <= 0:
        raise ValueError("total confidence is zero")
    weighted = sum(SENTIMENT_SCORES[r.sentiment] * r.confidence for r in results) / total_confidence
    return weighted, total_confidence / len(results)


def insert_interval_if_new(db: Session, values: dict[str, Any]) -> bool:
    """INSERT ... ON CONFLICT (job_id, timestamp) DO NOTHING. True if a row was added."""
    dialect = postgresql if db.get_bind().dialect.name == "postgresql" else sqlite
    statement = (
        dialect.insert(IntervalResultDB)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["job_id", "timestamp"])
    )
    return db.execute(statement).rowcount == 1


def handle_aggregation(
    payload: dict[str, Any],
    *,
    session_factory: SessionFactory,
    publish_to: Publisher,
    next_queue: str,
) -> None:
    metadata = {k: v for k, v in payload.items() if k != "results"}
    log = logger.bind(job_id=metadata.get("job_id"))

    results = [AnalysisOutput(**r) for r in payload["results"]]
    if not results:
        log.warning("no_results_to_aggregate")
        return
    interval_sentiment, interval_confidence = aggregate_interval(results)
    job_id = UUID(metadata["job_id"])

    with session_factory() as db:
        # A redelivered message hits the unique key and changes nothing.
        inserted = insert_interval_if_new(
            db,
            {
                "job_id": job_id,
                "timestamp": interval_time(metadata["interval_timestamp"]),
                "avg_sentiment": interval_sentiment,
                "avg_confidence": interval_confidence,
            },
        )
        db.commit()
        overall_sentiment, overall_confidence = (
            db.query(func.avg(IntervalResultDB.avg_sentiment), func.avg(IntervalResultDB.avg_confidence))
            .filter(IntervalResultDB.job_id == job_id)
            .one()
        )

    aggregate = Aggregate(
        interval_sentiment=interval_sentiment,
        interval_confidence=interval_confidence,
        overall_sentiment=float(overall_sentiment),
        overall_confidence=float(overall_confidence),
    )
    # Publish even when the row already existed: if an earlier attempt saved the
    # row but failed to publish, this retry is the only way the email gets sent.
    # Notification skips intervals it has already emailed.
    publish_to(next_queue, {**metadata, "aggregate": aggregate.model_dump()})
    log.info(
        "interval_aggregated" if inserted else "interval_already_stored",
        interval_sentiment=round(interval_sentiment, 3),
    )


def main() -> None:
    settings = get_settings(AggregationSettings)
    engine = create_engine(settings.db_url.get_secret_value(), pool_pre_ping=True)
    Base.metadata.create_all(bind=engine)  # removed in Task 1.7 (Alembic only)
    session_factory = sessionmaker(bind=engine)

    handler = partial(
        handle_aggregation,
        session_factory=session_factory,
        publish_to=publish,
        next_queue=settings.notification_queue,
    )
    consume(settings.aggregation_queue, handler)


if __name__ == "__main__":
    main()
