import json
from datetime import datetime, timezone
from types import SimpleNamespace

import boto3
import pytest
from botocore.stub import Stubber
from pydantic import ValidationError

from src.common.config import SchedulerSettings
from src.common.scheduler import EventBridgeScheduler, rate_expression

ROLE = "arn:aws:iam::123456789012:role/vibesense-scheduler"
QUEUE = "arn:aws:sqs:us-east-1:123456789012:vibesense-ingest"

JOB = SimpleNamespace(
    job_id="0b8a6f2e-1111-4222-8333-444455556666",
    post_id="vid123",
    intervals_seconds=4 * 3600,
    total_duration_seconds=24 * 3600,
    created_at=datetime(2026, 10, 29, 12, 0),  # naive UTC, as stored in the DB
)


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (60, "rate(1 minute)"),
        (300, "rate(5 minutes)"),
        (3600, "rate(1 hour)"),
        (4 * 3600, "rate(4 hours)"),
        (86400, "rate(1 day)"),
        (5400, "rate(90 minutes)"),
    ],
)
def test_rate_expression(seconds, expected):
    assert rate_expression(seconds) == expected


@pytest.mark.parametrize("seconds", [30, 90, 3600.5])
def test_rate_expression_rejects_non_minute_intervals(seconds):
    with pytest.raises(ValueError):
        rate_expression(seconds)


@pytest.fixture
def scheduler(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # ignore the project's .env
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    settings = SchedulerSettings(
        _env_file=None, scheduler_role_arn=ROLE, ingest_queue_arn=QUEUE, schedule_group="vibesense"
    )
    client = boto3.client("scheduler", region_name="us-east-1")
    with Stubber(client) as stub:
        yield EventBridgeScheduler(settings, client=client), stub
        stub.assert_no_pending_responses()


def test_create_sends_a_self_deleting_schedule_targeting_the_ingest_queue(scheduler):
    eventbridge, stub = scheduler
    stub.add_response(
        "create_schedule",
        {"ScheduleArn": "arn:aws:scheduler:us-east-1:123456789012:schedule/vibesense/job-x"},
        expected_params={
            "Name": f"job-{JOB.job_id}",
            "GroupName": "vibesense",
            "ScheduleExpression": "rate(4 hours)",
            "EndDate": datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc),
            "ActionAfterCompletion": "DELETE",
            "FlexibleTimeWindow": {"Mode": "OFF"},
            "State": "ENABLED",
            "Target": {
                "Arn": QUEUE,
                "RoleArn": ROLE,
                "Input": json.dumps({"job_id": JOB.job_id, "post_id": "vid123"}),
                "RetryPolicy": {"MaximumRetryAttempts": 3, "MaximumEventAgeInSeconds": 3600},
            },
        },
    )
    eventbridge.create_job_schedule(JOB)


def test_create_treats_an_existing_schedule_as_success(scheduler):
    eventbridge, stub = scheduler
    stub.add_client_error("create_schedule", service_error_code="ConflictException")
    eventbridge.create_job_schedule(JOB)  # no exception


def test_delete_ignores_a_schedule_that_is_already_gone(scheduler):
    eventbridge, stub = scheduler
    stub.add_client_error(
        "delete_schedule",
        service_error_code="ResourceNotFoundException",
        expected_params={"Name": f"job-{JOB.job_id}", "GroupName": "vibesense"},
    )
    eventbridge.delete_job_schedule(JOB.job_id)


def test_other_errors_are_raised(scheduler):
    eventbridge, stub = scheduler
    stub.add_client_error("create_schedule", service_error_code="AccessDeniedException")
    with pytest.raises(Exception):
        eventbridge.create_job_schedule(JOB)


def test_eventbridge_backend_requires_its_arns(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for name in ("SCHEDULER_BACKEND", "SCHEDULER_ROLE_ARN", "INGEST_QUEUE_ARN"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValidationError, match="scheduler_role_arn, ingest_queue_arn"):
        SchedulerSettings(_env_file=None)


def test_local_backend_needs_nothing(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert SchedulerSettings(_env_file=None, scheduler_backend="local").scheduler_backend == "local"
