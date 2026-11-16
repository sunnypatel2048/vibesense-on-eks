"""Prometheus metrics shared by every worker (served on /metrics by src/common/worker.py).

Defined once here: prometheus_client registers metrics globally, so defining
them in more than one module would fail at import.
"""
from prometheus_client import Counter, Gauge, Histogram

MESSAGES = Counter(
    "vibesense_messages",  # exposed as vibesense_messages_total
    "Messages handled, by queue and result (success or failure).",
    ["queue", "result"],
)

PROCESSING_SECONDS = Histogram(
    "vibesense_processing_seconds",
    "Time spent handling one message.",
    ["queue"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
)

LAST_SUCCESS = Gauge(
    "vibesense_last_success_timestamp_seconds",
    "Unix time a message on this queue was last handled successfully.",
    ["queue"],
)

PUBLISHED = Counter(
    "vibesense_messages_published",  # exposed as vibesense_messages_published_total
    "Messages sent, by destination queue.",
    ["queue"],
)

END_TO_END_SECONDS = Histogram(
    "vibesense_end_to_end_seconds",
    "From comments entering the pipeline (enqueued_at, set by ingestion or the load "
    "generator) to the interval being notified. The SLO's measurement (deploy/monitoring/slo-rules.yaml).",
    # 300 s is the SLO target, so it must be a bucket boundary exactly.
    buckets=(1, 2, 5, 10, 15, 30, 60, 90, 120, 180, 240, 300, 450, 600, 900, 1800),
)
