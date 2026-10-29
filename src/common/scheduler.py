"""One ingestion schedule per monitoring job.

In AWS each job gets an EventBridge Scheduler schedule that puts
{job_id, post_id} on the ingest queue every interval, stops at the job's end
date, and deletes itself after its last run. Locally the backend is a no-op;
the local scheduler process (src/local_scheduler) enqueues due jobs instead.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Protocol

import boto3
import structlog
from botocore.exceptions import ClientError

from src.common.config import SchedulerSettings, get_settings

logger = structlog.get_logger()


class ScheduledJob(Protocol):
    """The fields a schedule needs; MonitoringJobDB rows satisfy this."""

    job_id: Any
    post_id: str
    intervals_seconds: float
    total_duration_seconds: float
    created_at: datetime


def as_utc(value: datetime) -> datetime:
    """Database timestamps are naive UTC; make them timezone-aware."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def job_end(job: ScheduledJob) -> datetime:
    return as_utc(job.created_at) + timedelta(seconds=job.total_duration_seconds)


def rate_expression(interval_seconds: float) -> str:
    """EventBridge rate syntax: 'rate(1 hour)' but 'rate(4 hours)'."""
    seconds = int(interval_seconds)
    if seconds != interval_seconds or seconds < 60 or seconds % 60:
        raise ValueError(f"interval must be a whole number of minutes, got {interval_seconds}s")
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if seconds % size == 0:
            count = seconds // size
            return f"rate({count} {unit}{'' if count == 1 else 's'})"
    raise AssertionError("unreachable")


def schedule_name(job_id: Any) -> str:
    return f"job-{job_id}"


def ingest_message(job: ScheduledJob) -> dict[str, str]:
    """What every schedule run puts on the ingest queue."""
    return {"job_id": str(job.job_id), "post_id": job.post_id}


class EventBridgeScheduler:
    def __init__(self, settings: SchedulerSettings, client: Any = None) -> None:
        self.settings = settings
        self.client = client or boto3.client("scheduler", region_name=settings.aws_region)

    def create_job_schedule(self, job: ScheduledJob) -> None:
        name = schedule_name(job.job_id)
        try:
            self.client.create_schedule(
                Name=name,
                GroupName=self.settings.schedule_group,
                ScheduleExpression=rate_expression(job.intervals_seconds),
                EndDate=job_end(job),
                ActionAfterCompletion="DELETE",
                FlexibleTimeWindow={"Mode": "OFF"},
                State="ENABLED",
                Target={
                    "Arn": self.settings.ingest_queue_arn,
                    "RoleArn": self.settings.scheduler_role_arn,
                    "Input": json.dumps(ingest_message(job)),
                    "RetryPolicy": {"MaximumRetryAttempts": 3, "MaximumEventAgeInSeconds": 3600},
                },
            )
        except ClientError as error:
            if error.response["Error"]["Code"] != "ConflictException":
                raise
            # Already exists: a retried request is a success, not an error.
            logger.info("schedule_already_exists", schedule=name)
            return
        logger.info("schedule_created", schedule=name)

    def delete_job_schedule(self, job_id: Any) -> None:
        name = schedule_name(job_id)
        try:
            self.client.delete_schedule(Name=name, GroupName=self.settings.schedule_group)
        except ClientError as error:
            if error.response["Error"]["Code"] != "ResourceNotFoundException":
                raise
            logger.info("schedule_already_gone", schedule=name)
            return
        logger.info("schedule_deleted", schedule=name)


class LocalScheduler:
    """No-op backend for development; src/local_scheduler does the work."""

    def create_job_schedule(self, job: ScheduledJob) -> None:
        logger.info("local_schedule_skipped", job_id=str(job.job_id))

    def delete_job_schedule(self, job_id: Any) -> None:
        logger.info("local_schedule_delete_skipped", job_id=str(job_id))


@lru_cache
def get_scheduler() -> EventBridgeScheduler | LocalScheduler:
    settings = get_settings(SchedulerSettings)
    if settings.scheduler_backend == "local":
        return LocalScheduler()
    return EventBridgeScheduler(settings)
