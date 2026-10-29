"""Run a queue worker with /healthz, /readyz and /metrics on one small HTTP port.

Liveness has to tell *stuck* from *busy*: a worker scoring a big batch doesn't
poll for minutes, and that's fine. So:
  * idle: healthy if it polled (or finished a message) within max_idle_seconds
  * busy: healthy while the current message is younger than max_busy_seconds,
    which should match the queue's visibility timeout. Past that, SQS has
    already given the message to another worker, so this one is stuck or
    doing duplicate work, and restarting it is right.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Protocol

import structlog
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from src.common.queue import Consumer, Handler

logger = structlog.get_logger()


class HealthState(Protocol):
    last_activity: float
    busy_since: float | None
    has_polled: bool


@dataclass(frozen=True)
class HealthPolicy:
    max_idle_seconds: float = 60.0
    max_busy_seconds: float = 60.0


def check_health(state: HealthState, policy: HealthPolicy, now: float) -> tuple[bool, str]:
    if state.busy_since is not None:
        busy = now - state.busy_since
        return busy <= policy.max_busy_seconds, f"busy for {busy:.0f}s (limit {policy.max_busy_seconds:.0f}s)"
    idle = now - state.last_activity
    return idle <= policy.max_idle_seconds, f"last active {idle:.0f}s ago (limit {policy.max_idle_seconds:.0f}s)"


class _ProbeHandler(BaseHTTPRequestHandler):
    server: "_ProbeServer"

    def do_GET(self) -> None:  # noqa: N802 (http.server naming)
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            ok, detail = check_health(self.server.state, self.server.policy, time.monotonic())
            self._reply(200 if ok else 503, detail.encode())
        elif path == "/readyz":
            ready = self.server.state.has_polled
            self._reply(200 if ready else 503, b"ready" if ready else b"not polled yet")
        elif path == "/metrics":
            self._reply(200, generate_latest(), CONTENT_TYPE_LATEST)
        else:
            self._reply(404, b"not found")

    def _reply(self, status: int, body: bytes, content_type: str = "text/plain; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        pass  # probes hit this every few seconds; keep them out of the logs


class _ProbeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int, state: HealthState, policy: HealthPolicy) -> None:
        super().__init__(("0.0.0.0", port), _ProbeHandler)
        self.state = state
        self.policy = policy


class ProbeServer:
    """The worker's HTTP endpoints, served from a background thread."""

    def __init__(self, state: HealthState, port: int, policy: HealthPolicy) -> None:
        self._server = _ProbeServer(port, state, policy)
        self._thread = threading.Thread(target=self._server.serve_forever, name="probe-server", daemon=True)

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    def start(self) -> None:
        self._thread.start()
        logger.info("probe_server_started", port=self.port)

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def run_worker(
    queue_name: str,
    handler: Handler,
    *,
    port: int,
    max_busy_seconds: float = 60.0,
    **consumer_options: Any,
) -> None:
    """Consume `queue_name` until SIGTERM, serving probes and metrics on `port`."""
    consumer = Consumer(queue_name, handler, **consumer_options)
    server = ProbeServer(consumer, port, HealthPolicy(max_busy_seconds=max_busy_seconds))
    server.start()
    try:
        consumer.run()
    finally:
        server.stop()
