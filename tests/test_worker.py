import time
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

from src.common.worker import HealthPolicy, ProbeServer, check_health

POLICY = HealthPolicy(max_idle_seconds=60, max_busy_seconds=300)
NOW = 10_000.0


def state(*, last_activity=NOW, busy_since=None, has_polled=True):
    return SimpleNamespace(last_activity=last_activity, busy_since=busy_since, has_polled=has_polled)


# --- Health rules --------------------------------------------------------------

def test_recently_active_idle_worker_is_healthy():
    ok, _ = check_health(state(last_activity=NOW - 20), POLICY, NOW)
    assert ok


def test_idle_worker_that_stopped_polling_is_unhealthy():
    ok, detail = check_health(state(last_activity=NOW - 61), POLICY, NOW)
    assert not ok
    assert "last active" in detail


def test_long_running_message_within_its_limit_is_healthy():
    # Hasn't polled for 4 minutes, but it's busy with one message: not stuck.
    ok, _ = check_health(state(last_activity=NOW - 240, busy_since=NOW - 240), POLICY, NOW)
    assert ok


def test_message_running_past_its_limit_is_unhealthy():
    ok, detail = check_health(state(busy_since=NOW - 301), POLICY, NOW)
    assert not ok
    assert "busy for" in detail


# --- HTTP endpoints ------------------------------------------------------------

def get(port, path):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


@pytest.fixture
def serve():
    servers = []

    def start(probe_state):
        server = ProbeServer(probe_state, port=0, policy=POLICY)  # port 0: any free port
        server.start()
        servers.append(server)
        return server.port

    yield start
    for server in servers:
        server.stop()


def test_healthz_and_readyz_for_a_working_consumer(serve):
    port = serve(state(last_activity=time.monotonic() - 5))
    assert get(port, "/healthz")[0] == 200
    assert get(port, "/readyz")[0] == 200


def test_healthz_fails_for_a_stuck_consumer(serve):
    port = serve(state(last_activity=time.monotonic() - 600))
    assert get(port, "/healthz")[0] == 503


def test_not_ready_until_the_first_poll(serve):
    port = serve(state(last_activity=time.monotonic(), has_polled=False))
    assert get(port, "/readyz") == (503, "not polled yet")


def test_metrics_endpoint_serves_prometheus_text(serve):
    import src.common.metrics  # noqa: F401  (registers the vibesense_* metrics)

    status, body = get(serve(state(last_activity=time.monotonic())), "/metrics")
    assert status == 200
    assert "vibesense_messages_total" in body


def test_unknown_path_is_404(serve):
    assert get(serve(state(last_activity=time.monotonic())), "/nope")[0] == 404
