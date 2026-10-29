"""Structured logging for every service.

One format for everything: our structlog calls *and* library logs (boto3,
SQLAlchemy, Alembic) go through the same processors, so in Kubernetes every
line is one JSON object with timestamp, level, service and event.

Values bound with structlog.contextvars (the queue consumer binds job_id and
message_id while handling a message) appear on every line written meanwhile,
from any module, so one job can be followed across all services.
"""
import logging
import sys
from typing import Any, TextIO

import structlog
from structlog.typing import EventDict, WrappedLogger

from src.common.config import LoggingSettings, get_settings

# Libraries that are chatty at INFO and rarely useful there.
_QUIET_LOGGERS = ("botocore", "boto3", "urllib3", "googleapiclient.discovery_cache")


def _add_service(service: str):
    def processor(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
        event_dict.setdefault("service", service)
        return event_dict

    return processor


def configure_logging(
    service: str,
    *,
    log_format: str | None = None,
    level: str | None = None,
    stream: TextIO | None = None,
) -> None:
    """Call once at the top of each service's main(). Arguments override settings."""
    if log_format is None or level is None:
        settings = get_settings(LoggingSettings)
        log_format = log_format or settings.log_format
        level = level or settings.log_level

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_service(service),
    ]

    if log_format == "json":
        final: list[Any] = [structlog.processors.format_exc_info, structlog.processors.JSONRenderer()]
    else:
        final = [structlog.dev.ConsoleRenderer()]

    structlog.configure(
        processors=[
            *shared,
            structlog.processors.StackInfoRenderer(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )

    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,  # library log records get the same fields
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, *final],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
