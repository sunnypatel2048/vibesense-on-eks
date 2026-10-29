from datetime import datetime, timezone

import pytest

from src.common.scheduler import rate_expression
from src.models import MonitoringJobDB
from src.ui_service.jobs import (
    DEMO_PLAN,
    PLANS,
    FormError,
    JobRequest,
    available_plans,
    create_job,
    humanize,
    validate_request,
)

NOW = datetime(2026, 10, 29, 15, 0, tzinfo=timezone.utc)
REQUEST = JobRequest(full_name="Ada Lovelace", email="ada@gmail.com", video_id="vid123")


# --- Plans -------------------------------------------------------------------

@pytest.mark.parametrize("plan", [*PLANS, DEMO_PLAN], ids=lambda p: p.key)
def test_every_plan_is_a_valid_eventbridge_schedule(plan):
    rate_expression(plan.interval_seconds)  # raises if EventBridge would reject it
    assert plan.total_seconds % plan.interval_seconds == 0


def test_demo_plan_only_appears_in_demo_mode():
    assert DEMO_PLAN not in available_plans(demo_mode=False)
    assert available_plans(demo_mode=True)[0] == DEMO_PLAN


@pytest.mark.parametrize(
    "seconds, text",
    [(300, "5 minutes"), (3600, "1 hour"), (4 * 3600, "4 hours"), (86400, "24 hours"), (3 * 86400, "3 days")],
)
def test_humanize(seconds, text):
    assert humanize(seconds) == text


def test_plan_description():
    assert PLANS[0].description == "Every 4 hours for 24 hours"
    assert DEMO_PLAN.description == "Every 5 minutes for 30 minutes"


# --- Validation --------------------------------------------------------------

def test_valid_request_is_cleaned():
    request = validate_request("  Ada  ", " ada@gmail.com ", " https://youtu.be/vid123 ")
    assert request == JobRequest(full_name="Ada", email="ada@gmail.com", video_id="vid123")


@pytest.mark.parametrize(
    "name, email, url, field",
    [
        ("Ada", "ada@gmail.com", "https://vimeo.com/123", "url"),
        ("   ", "ada@gmail.com", "https://youtu.be/vid123", "name"),
        ("Ada", "not-an-email", "https://youtu.be/vid123", "email"),
    ],
)
def test_invalid_requests_name_the_problem_field(name, email, url, field):
    with pytest.raises(FormError) as error:
        validate_request(name, email, url)
    assert error.value.field == field


# --- Creating a job ------------------------------------------------------------

class FakeScheduler:
    def __init__(self, fail=False):
        self.fail = fail
        self.scheduled = []

    def create_job_schedule(self, job):
        if self.fail:
            raise RuntimeError("EventBridge unavailable")
        self.scheduled.append((str(job.job_id), job.intervals_seconds))


def stored_jobs(session_factory):
    with session_factory() as db:
        return db.query(MonitoringJobDB).all()


def test_job_is_saved_scheduled_and_kicked_off(session_factory, published):
    scheduler = FakeScheduler()

    created = create_job(
        REQUEST, title="My video", plan=PLANS[0], session_factory=session_factory,
        scheduler=scheduler, publish_to=published, ingest_queue="ingest", now=NOW,
    )

    [row] = stored_jobs(session_factory)
    assert row.is_scheduled is True
    assert (row.post_id, row.post_title, row.email) == ("vid123", "My video", "ada@gmail.com")
    assert scheduler.scheduled == [(str(created.job_id), 4 * 3600)]
    assert published.calls == [("ingest", {"job_id": str(created.job_id), "post_id": "vid123"})]
    assert created.first_report_now is True
    assert created.ends_at == datetime(2026, 10, 30, 15, 0, tzinfo=timezone.utc)


def test_scheduling_failure_removes_the_job(session_factory, published):
    with pytest.raises(RuntimeError):
        create_job(
            REQUEST, title="My video", plan=PLANS[0], session_factory=session_factory,
            scheduler=FakeScheduler(fail=True), publish_to=published, ingest_queue="ingest", now=NOW,
        )
    assert stored_jobs(session_factory) == []
    assert published.calls == []


def test_failed_kick_off_still_keeps_the_scheduled_job(session_factory):
    def broken_publish(queue, payload):
        raise RuntimeError("queue unavailable")

    created = create_job(
        REQUEST, title="My video", plan=PLANS[0], session_factory=session_factory,
        scheduler=FakeScheduler(), publish_to=broken_publish, ingest_queue="ingest", now=NOW,
    )

    assert created.first_report_now is False
    [row] = stored_jobs(session_factory)
    assert row.is_scheduled is True
