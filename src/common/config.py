"""Typed, validated configuration for every VibeSense service.

Values come from real environment variables first, then from a local `.env`
file (development only; in Kubernetes there is no `.env`). Each service loads
its own settings class, built from only the blocks it needs, so a missing or
malformed value stops the service at startup with one error naming every
problem, instead of crashing mid-message later.

Secrets are `SecretStr`: they print as '**********'. Call `.get_secret_value()`
only at the point where the value is actually used.
"""
from functools import lru_cache
from typing import Any, Literal, TypeVar

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class _BaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # .env holds variables for every service
    )

    @field_validator("*")
    @classmethod
    def _reject_blank(cls, value: Any) -> Any:
        """Treat `VAR=` (set but empty) the same as missing."""
        raw = value.get_secret_value() if isinstance(value, SecretStr) else value
        if isinstance(raw, str) and not raw.strip():
            raise ValueError("must not be empty")
        return value


# --- Building blocks -------------------------------------------------------

class DatabaseSettings(_BaseSettings):
    db_url: SecretStr  # DB_URL; contains the password


class YouTubeSettings(_BaseSettings):
    youtube_api_key: SecretStr  # YOUTUBE_API_KEY


class SmtpSettings(_BaseSettings):
    smtp_server: str        # SMTP_SERVER
    smtp_port: int = 587    # SMTP_PORT
    smtp_user: str          # SMTP_USER
    smtp_pass: SecretStr    # SMTP_PASS

    @property
    def from_email(self) -> str:
        return self.smtp_user


class QueueSettings(_BaseSettings):
    """SQS queues, addressed by name; the URL is looked up once at startup.

    Names are the same locally (ElasticMQ) and in AWS, so only the endpoint
    differs between environments.
    """

    aws_region: str = "us-east-1"                        # AWS_REGION
    ingest_queue: str = "vibesense-ingest"               # INGEST_QUEUE
    analysis_queue: str = "vibesense-analysis"           # ANALYSIS_QUEUE
    aggregation_queue: str = "vibesense-aggregation"     # AGGREGATION_QUEUE
    notification_queue: str = "vibesense-notification"   # NOTIFICATION_QUEUE
    # Local development only: point at ElasticMQ, e.g. http://localhost:9324.
    # Leave unset in AWS so boto3 uses real SQS.
    sqs_endpoint_url: str | None = None                  # SQS_ENDPOINT_URL


class SchedulerSettings(_BaseSettings):
    """Per-job ingestion schedules.

    `eventbridge` (the default, used in AWS) creates one EventBridge Scheduler
    schedule per job. `local` is a no-op: in development the local scheduler
    process (src/local_scheduler) enqueues due jobs instead.
    """

    scheduler_backend: Literal["eventbridge", "local"] = "eventbridge"  # SCHEDULER_BACKEND
    aws_region: str = "us-east-1"                                       # AWS_REGION
    schedule_group: str = "vibesense"                                   # SCHEDULE_GROUP
    scheduler_role_arn: str | None = None                               # SCHEDULER_ROLE_ARN
    ingest_queue_arn: str | None = None                                 # INGEST_QUEUE_ARN

    @model_validator(mode="after")
    def _eventbridge_needs_targets(self) -> "SchedulerSettings":
        if self.scheduler_backend == "eventbridge":
            missing = [
                name for name in ("scheduler_role_arn", "ingest_queue_arn") if not getattr(self, name)
            ]
            if missing:
                raise ValueError(
                    f"{', '.join(missing)} required when SCHEDULER_BACKEND=eventbridge"
                )
        return self


# --- One class per service -------------------------------------------------

class UiSettings(DatabaseSettings, YouTubeSettings, QueueSettings, SchedulerSettings):
    demo_mode: bool = False  # DEMO_MODE; adds a 30-minute plan with 5-minute reports


class IngestionSettings(DatabaseSettings, YouTubeSettings, QueueSettings):
    pass


class AiSettings(QueueSettings):
    pass


class AggregationSettings(DatabaseSettings, QueueSettings):
    pass


class NotificationSettings(DatabaseSettings, SmtpSettings, QueueSettings):
    pass


# Development only: the stand-in for EventBridge Scheduler.
class LocalSchedulerSettings(DatabaseSettings, QueueSettings):
    pass


# Alembic migrations only need the database.
MigrationSettings = DatabaseSettings


S = TypeVar("S", bound=_BaseSettings)


@lru_cache
def get_settings(settings_cls: type[S]) -> S:
    """Load a settings class once per process and reuse it.

    Tests call `get_settings.cache_clear()` after changing the environment.
    """
    return settings_cls()
