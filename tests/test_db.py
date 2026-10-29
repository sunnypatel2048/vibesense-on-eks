import pytest
from sqlalchemy import create_engine, text

from src.common.db import SchemaOutOfDateError, check_schema_current, expected_revisions


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'schema.db'}")
    yield engine
    engine.dispose()


def stamp(engine, revision):
    """Record `revision` the way `alembic upgrade` does, without running SQL
    (the real migrations are PostgreSQL-specific)."""
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(text("DELETE FROM alembic_version"))
        connection.execute(text("INSERT INTO alembic_version VALUES (:rev)"), {"rev": revision})


def test_migrations_have_exactly_one_head():
    # Two heads means two branches of migrations were merged without being
    # reconciled; `alembic upgrade head` would refuse to run.
    assert len(expected_revisions()) == 1


def test_database_at_head_passes(engine):
    [head] = expected_revisions()
    stamp(engine, head)
    check_schema_current(engine)


def test_database_behind_fails_naming_both_revisions(engine):
    stamp(engine, "2491a531b839")  # the revision before interval idempotency
    [head] = expected_revisions()
    with pytest.raises(SchemaOutOfDateError) as error:
        check_schema_current(engine)
    assert "2491a531b839" in str(error.value)
    assert head in str(error.value)
    assert "alembic upgrade head" in str(error.value)


def test_never_migrated_database_fails(engine):
    with pytest.raises(SchemaOutOfDateError, match="never migrated"):
        check_schema_current(engine)


def test_database_ahead_of_code_is_allowed(engine):
    stamp(engine, "ffffffffffff")  # a migration from a newer release
    check_schema_current(engine)  # warns, doesn't raise
