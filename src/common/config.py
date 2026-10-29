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
from typing import Any, TypeVar

from pydantic import SecretStr, field_validator
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


# Legacy: removed when RabbitMQ is replaced by SQS (Tasks 1.2-1.3).
class LegacyRabbitMQSettings(_BaseSettings):
    rabbitmq_url: SecretStr  # RABBITMQ_URL; may contain credentials


# Legacy: removed when Celery Beat/RedBeat are replaced (Task 1.4).
class LegacyRedisSettings(_BaseSettings):
    redis_url: SecretStr  # REDIS_URL


# --- One class per service -------------------------------------------------

class UiSettings(DatabaseSettings, YouTubeSettings, LegacyRabbitMQSettings):
    pass


class IngestionSettings(
    DatabaseSettings, YouTubeSettings, LegacyRabbitMQSettings, LegacyRedisSettings
):
    pass


class AiSettings(LegacyRabbitMQSettings):
    pass


class AggregationSettings(DatabaseSettings, LegacyRabbitMQSettings):
    pass


class NotificationSettings(DatabaseSettings, SmtpSettings, LegacyRabbitMQSettings):
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
