from pydantic import BaseModel, EmailStr, validator
from datetime import datetime, timedelta, timezone
from typing import Dict, Tuple
from sqlalchemy import Column, String, Float, Boolean, DateTime, ForeignKey, JSON, UniqueConstraint, Uuid
from sqlalchemy.ext.declarative import declarative_base
from uuid import uuid4

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
    created_at = Column(DateTime, default=datetime.now(timezone.utc))

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
    raw_comments = Column(JSON)  # Store list of CommentData JSON for history
    notified_at = Column(DateTime)  # set once this interval's email is sent


def interval_time(value: str) -> datetime:
    """Interval timestamps travel between services as ISO strings
    ('2026-10-29T13:30:00Z') and are stored as naive UTC. Aggregation and
    notification both use this so they always agree on an interval's key."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)

# Pydantic Models (for API/Validation)
class UserInput(BaseModel):
    full_name: str
    post_url: str
    email: EmailStr
    duration: str  # e.g., "1 day 4 hour"

class MonitoringJob(BaseModel):
    job_id: str  # UUID as string
    post_id: str
    post_title: str
    intervals: float
    total_duration: float
    email: EmailStr
    user_full_name: str

class CommentData(BaseModel):
    comment_id: str
    text: str
    published_at: datetime
    metrics: Dict[str, int]  # e.g., {'like_count': int}

class AnalysisOutput(BaseModel):
    text: str
    sentiment: str  # "POSITIVE", "NEGATIVE"
    confidence: float

class Aggregate(BaseModel):
    interval_sentiment: float
    overall_sentiment: float
    interval_confidence: float
    overall_confidence: float