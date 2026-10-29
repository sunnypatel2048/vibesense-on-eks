"""Creating a monitoring job: validation, plans, and the save/schedule/kick-off
sequence. Kept free of Streamlit so it can be unit-tested."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID, uuid4

import structlog
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from src.common.scheduler import ingest_message, job_end
from src.models import MonitoringJobDB
from src.utils import parse_youtube_video_id

logger = structlog.get_logger()

Publisher = Callable[[str, dict[str, Any]], Any]
SessionFactory = Callable[[], Session]

HOUR = 3600
DAY = 24 * HOUR


def humanize(seconds: float) -> str:
    """5 minutes, 4 hours, 24 hours, 3 days."""
    seconds = int(seconds)
    if seconds > DAY and seconds % DAY == 0:
        n, unit = seconds // DAY, "day"
    elif seconds % HOUR == 0:
        n, unit = seconds // HOUR, "hour"
    else:
        n, unit = seconds // 60, "minute"
    return f"{n} {unit}{'' if n == 1 else 's'}"


@dataclass(frozen=True)
class Plan:
    key: str
    label: str
    total_seconds: int
    interval_seconds: int

    @property
    def description(self) -> str:
        return f"Every {humanize(self.interval_seconds)} for {humanize(self.total_seconds)}"

    @property
    def report_count(self) -> int:
        return self.total_seconds // self.interval_seconds


PLANS = (
    Plan("1d", "1 day", 1 * DAY, 4 * HOUR),
    Plan("3d", "3 days", 3 * DAY, 8 * HOUR),
    Plan("1w", "1 week", 7 * DAY, 24 * HOUR),
)
DEMO_PLAN = Plan("demo", "Demo", 30 * 60, 5 * 60)


def available_plans(demo_mode: bool) -> list[Plan]:
    return [DEMO_PLAN, *PLANS] if demo_mode else list(PLANS)


# --- Validation ----------------------------------------------------------------

class FormError(ValueError):
    """A problem with what the user typed; `message` is safe to show them."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


_email = TypeAdapter(EmailStr)


@dataclass(frozen=True)
class JobRequest:
    full_name: str
    email: str
    video_id: str


def validate_request(full_name: str, email: str, video_url: str) -> JobRequest:
    try:
        video_id = parse_youtube_video_id(video_url.strip())
    except ValueError:
        raise FormError("url", "That doesn't look like a YouTube video link.") from None

    name = full_name.strip()
    if not name:
        raise FormError("name", "Enter your name.")

    try:
        clean_email = _email.validate_python(email.strip())
    except ValidationError:
        raise FormError("email", "Enter a valid email address.") from None

    return JobRequest(full_name=name, email=clean_email, video_id=video_id)


# --- Creating the job --------------------------------------------------------------

@dataclass(frozen=True)
class CreatedJob:
    job_id: UUID
    ends_at: datetime
    first_report_now: bool


def create_job(
    request: JobRequest,
    *,
    title: str,
    plan: Plan,
    session_factory: SessionFactory,
    scheduler: Any,
    publish_to: Publisher,
    ingest_queue: str,
    now: datetime | None = None,
) -> CreatedJob:
    """Save the job, schedule it, and kick off the first report.

    If scheduling fails the row is deleted, so a job never exists without a
    schedule. If only the immediate kick-off fails, the job still stands and its
    first report simply arrives after one interval.
    """
    now = now or datetime.now(timezone.utc)

    with session_factory() as db:
        job = MonitoringJobDB(
            job_id=uuid4(),
            post_id=request.video_id,
            post_title=title,
            user_full_name=request.full_name,
            email=request.email,
            intervals_seconds=plan.interval_seconds,
            total_duration_seconds=plan.total_seconds,
            created_at=now.astimezone(timezone.utc).replace(tzinfo=None),  # naive UTC, like the rest
            last_fetched_at=None,
            is_scheduled=False,
        )
        db.add(job)
        db.commit()
        log = logger.bind(job_id=str(job.job_id))

        try:
            scheduler.create_job_schedule(job)
        except Exception:
            log.exception("schedule_failed_rolling_back")
            db.delete(job)
            db.commit()
            raise

        job.is_scheduled = True
        db.commit()
        result_id, ends_at, first_message = job.job_id, job_end(job), ingest_message(job)

    try:
        publish_to(ingest_queue, first_message)
        first_report_now = True
    except Exception:
        log.exception("first_ingest_failed")
        first_report_now = False

    log.info("job_created", plan=plan.key)
    return CreatedJob(job_id=result_id, ends_at=ends_at, first_report_now=first_report_now)
