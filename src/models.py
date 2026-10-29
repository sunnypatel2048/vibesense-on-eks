from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, JSON, String, UniqueConstraint, Uuid
from sqlalchemy.orm import declarative_base

Base = declarative_base()

# DB Tables (Schema)
class MonitoringJobDB(Base):
    __tablename__ = "monitoring_jobs"
    job_id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    post_id = Column(String, nullable=False)
    post_title = Column(String)
    user_full_name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    intervals_seconds = Column(Float, nullable=False)  # e.g., 14400 for 4 hours
    total_duration_seconds = Column(Float, nullable=False)  # e.g., 86400 for 1 day
    is_scheduled = Column(Boolean, default=False)
    last_fetched_at = Column(DateTime, default=None)
    # A callable, so it runs per row. (`datetime.now(...)` without the lambda would be
    # evaluated once at import, giving every row the process start time.)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

class IntervalResultDB(Base):
    __tablename__ = "interval_results"
    # One row per job per interval: a redelivered message can't add a second
    # row (which would also skew the job's overall average).
    __table_args__ = (
        UniqueConstraint("job_id", "timestamp", name="uq_interval_results_job_timestamp"),
    )
    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    job_id = Column(Uuid(as_uuid=True), ForeignKey("monitoring_jobs.job_id"), nullable=False)
    timestamp = Column(DateTime, nullable=False)
    avg_sentiment = Column(Float)
    avg_confidence = Column(Float)
    summary = Column(String)
    raw_comments = Column(JSON)  # unused; kept to match the existing schema
    notified_at = Column(DateTime)  # set once this interval's email is sent


def interval_time(value: str) -> datetime:
    """Interval timestamps travel between services as ISO strings
    ('2026-10-29T13:30:00Z') and are stored as naive UTC. Aggregation and
    notification both use this so they always agree on an interval's key."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)

# Messages passed between workers
class AnalysisOutput(BaseModel):
    text: str
    sentiment: str  # "POSITIVE", "NEGATIVE"
    confidence: float

class Aggregate(BaseModel):
    interval_sentiment: float
    overall_sentiment: float
    interval_confidence: float
    overall_confidence: float