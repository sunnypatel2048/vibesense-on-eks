import io
import json
import logging

import pytest
import structlog

from src.common.logs import configure_logging


@pytest.fixture
def capture():
    """Configure logging into a buffer, and put everything back afterwards."""
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    buffer = io.StringIO()

    def lines():
        return [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]

    def setup(service="ai", log_format="json"):
        configure_logging(service, log_format=log_format, level="INFO", stream=buffer)
        return lines

    yield setup

    root.handlers, root.level = saved_handlers, saved_level
    structlog.contextvars.clear_contextvars()
    structlog.reset_defaults()


def test_json_lines_carry_standard_fields(capture):
    lines = capture(service="ai")
    structlog.get_logger().info("comments_scored", count=3)

    [line] = lines()
    assert line["event"] == "comments_scored"
    assert line["count"] == 3
    assert line["service"] == "ai"
    assert line["level"] == "info"
    assert line["timestamp"].endswith("Z")


def test_library_logs_use_the_same_json_format(capture):
    lines = capture(service="notification")
    logging.getLogger("sqlalchemy.pool").warning("connection dropped")

    [line] = lines()
    assert line["event"] == "connection dropped"
    assert line["service"] == "notification"
    assert line["level"] == "warning"


def test_bound_context_appears_on_library_lines_too(capture):
    lines = capture()
    structlog.contextvars.bind_contextvars(job_id="job-1")
    logging.getLogger("some.library").warning("retrying")
    structlog.contextvars.clear_contextvars()

    assert lines()[0]["job_id"] == "job-1"


def test_exceptions_are_rendered_into_the_json(capture):
    lines = capture()
    try:
        raise ValueError("boom")
    except ValueError:
        structlog.get_logger().exception("message_failed")

    [line] = lines()
    assert "ValueError: boom" in line["exception"]


def test_quiet_libraries_drop_info(capture):
    lines = capture()
    logging.getLogger("botocore.credentials").info("Found credentials in environment variables.")
    assert lines() == []


def test_console_format_is_human_readable(capture):
    configure_logging("ai", log_format="console", level="INFO", stream=(buffer := io.StringIO()))
    structlog.get_logger().info("hello", job_id="job-1")
    output = buffer.getvalue()
    assert "hello" in output and "job-1" in output
    with pytest.raises(json.JSONDecodeError):
        json.loads(output.splitlines()[0])
