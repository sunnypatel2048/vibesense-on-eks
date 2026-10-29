"""Database access shared by every service.

Alembic is the only thing that changes the schema. Services never create
tables; at startup they check the database has the migrations their code
needs, and refuse to start if it doesn't.
"""
from pathlib import Path

import structlog
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from src.common.config import DatabaseSettings

logger = structlog.get_logger()

REPO_ROOT = Path(__file__).resolve().parents[2]


class SchemaOutOfDateError(RuntimeError):
    """The database is missing migrations this code depends on."""


def _scripts() -> ScriptDirectory:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    return ScriptDirectory.from_config(config)


def expected_revisions() -> set[str]:
    """The latest migration(s) in this codebase."""
    return set(_scripts().get_heads())


def current_revisions(engine: Engine) -> set[str]:
    """The migration(s) the database has been upgraded to."""
    with engine.connect() as connection:
        return set(MigrationContext.configure(connection).get_current_heads())


def check_schema_current(engine: Engine) -> None:
    scripts = _scripts()
    expected = set(scripts.get_heads())
    current = current_revisions(engine)

    if current == expected:
        return

    known = {revision.revision for revision in scripts.walk_revisions()}
    if current and not current <= known:
        # The database has a migration this code doesn't know: a newer release
        # already migrated it (e.g. during a rollback). Backward-compatible
        # migrations make that safe, so warn rather than refuse.
        logger.warning("database_schema_ahead_of_code", database=sorted(current), code=sorted(expected))
        return

    at = ", ".join(sorted(current)) if current else "no revision (never migrated)"
    raise SchemaOutOfDateError(
        f"Database schema is at {at}, but this code needs {', '.join(sorted(expected))}. "
        "Run `alembic upgrade head`."
    )


def create_session_factory(settings: DatabaseSettings, *, check_schema: bool = True) -> sessionmaker:
    """One engine per process, with dropped connections detected and replaced."""
    engine = create_engine(settings.db_url.get_secret_value(), pool_pre_ping=True)
    if check_schema:
        check_schema_current(engine)
    return sessionmaker(bind=engine)
