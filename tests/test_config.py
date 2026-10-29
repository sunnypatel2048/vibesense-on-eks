import pytest
from pydantic import ValidationError

from src.common.config import (
    AggregationSettings,
    AiSettings,
    NotificationSettings,
    UiSettings,
    get_settings,
)

ALL_VARS = {
    "DB_URL": "postgresql://user:db-secret@localhost/vibesense",
    "YOUTUBE_API_KEY": "yt-secret",
    "SMTP_SERVER": "smtp.example.com",
    "SMTP_PORT": "2525",
    "SMTP_USER": "bot@example.com",
    "SMTP_PASS": "smtp-secret",
}


@pytest.fixture
def env(monkeypatch):
    """Start every test from a known environment, ignoring the local .env."""
    for name in ALL_VARS:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


def set_all(monkeypatch, **overrides):
    for name, value in {**ALL_VARS, **overrides}.items():
        monkeypatch.setenv(name, value)


def test_loads_and_types_values_from_environment(env):
    set_all(env)
    s = NotificationSettings(_env_file=None)
    assert s.smtp_server == "smtp.example.com"
    assert s.smtp_port == 2525  # converted to int
    assert s.from_email == "bot@example.com"
    assert s.db_url.get_secret_value() == ALL_VARS["DB_URL"]


def test_smtp_port_defaults_to_587(env):
    set_all(env)
    env.delenv("SMTP_PORT")
    assert NotificationSettings(_env_file=None).smtp_port == 587


def test_missing_required_value_names_the_field(env):
    set_all(env)
    env.delenv("DB_URL")
    with pytest.raises(ValidationError) as exc:
        AggregationSettings(_env_file=None)
    assert "db_url" in str(exc.value)


def test_every_missing_value_is_reported_at_once(env):
    with pytest.raises(ValidationError) as exc:
        UiSettings(_env_file=None)
    missing = {err["loc"][0] for err in exc.value.errors()}
    assert missing == {"db_url", "youtube_api_key"}


def test_blank_value_is_rejected(env):
    set_all(env, SMTP_USER="   ")
    with pytest.raises(ValidationError) as exc:
        NotificationSettings(_env_file=None)
    assert "smtp_user" in str(exc.value)


def test_service_only_requires_what_it_uses(env):
    s = AiSettings(_env_file=None)  # no DB, SMTP, YouTube or broker needed
    assert s.analysis_queue == "vibesense-analysis"


def test_secrets_are_hidden_when_printed(env):
    set_all(env)
    text = repr(NotificationSettings(_env_file=None))
    for secret in ("db-secret", "smtp-secret"):
        assert secret not in text


def test_get_settings_returns_the_same_instance(env):
    set_all(env)
    assert get_settings(AiSettings) is get_settings(AiSettings)
