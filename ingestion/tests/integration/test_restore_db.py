"""The restore between two real databases (F7.2).

Source: TEST_DATABASE_URL with the fixture dump loaded. Target: a second
database created on the same server and migrated like Neon would be. Skipped
unless TEST_DATABASE_URL is set (its user must be able to CREATE DATABASE).
"""

import os
import subprocess
from collections.abc import Iterator
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

import restore as restore_module
from common.size_guard import SizeGuard, SizeLimitError, database_size
from restore import EXCLUDED_TABLES, RestoreError, data_tables, restore
from structured.checks import Check
from structured.config import REPO_ROOT, normalise_database_url
from structured.load import load
from structured.transform import transform
from tests.fixture_dump import FakeSource

pytestmark = pytest.mark.integration

_RAW_URL = os.environ.get("TEST_DATABASE_URL")
if not _RAW_URL:
    pytest.skip("TEST_DATABASE_URL not set", allow_module_level=True)

SOURCE_URL = normalise_database_url(_RAW_URL)
_parts = urlsplit(SOURCE_URL)
TARGET_DB = _parts.path.strip("/") + "_restore_target"
TARGET_URL = urlunsplit(_parts._replace(path=f"/{TARGET_DB}"))
ADMIN_URL = urlunsplit(_parts._replace(path="/postgres"))

# Passes on the fixture data (the real CHECKS assert full-data facts).
PASSING = (Check("races loaded", "SELECT count(*) > 0 FROM races", True),)
FAILING = (Check("impossible", "SELECT count(*) FROM races", -1),)


def _migrate(url: str) -> None:
    subprocess.run(  # noqa: S603
        ["uv", "run", "--frozen", "alembic", "upgrade", "head"],  # noqa: S607
        cwd=REPO_ROOT / "backend",
        env={**os.environ, "DATABASE_URL": url},
        check=True,
        capture_output=True,
    )


@pytest.fixture(scope="module", autouse=True)
def databases() -> Iterator[None]:
    _migrate(SOURCE_URL)
    with psycopg.connect(SOURCE_URL) as conn:
        load(conn, transform(FakeSource()), 1950, 2025)
        # Operational data the restore must leave behind.
        conn.execute(
            "INSERT INTO feedback (rating, question, answer_excerpt) "
            "VALUES ('up', 'q?', 'a')"
        )
        conn.commit()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{TARGET_DB}"')
        admin.execute(f'CREATE DATABASE "{TARGET_DB}"')
    _migrate(TARGET_URL)
    yield
    with psycopg.connect(SOURCE_URL, autocommit=True) as conn:
        conn.execute("TRUNCATE feedback")
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{TARGET_DB}" WITH (FORCE)')


@pytest.fixture
def empty_target() -> None:
    with psycopg.connect(TARGET_URL, autocommit=True) as conn:
        tables = data_tables(conn.cursor())
        conn.execute(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE")


def _counts(url: str) -> dict[str, int]:
    with psycopg.connect(url) as conn:
        cur = conn.cursor()
        return {
            t: cur.execute(f"SELECT count(*) FROM {t}").fetchone()[0]  # noqa: S608
            for t in data_tables(cur)
        }


def _restore(**kwargs: object):  # noqa: ANN202
    kwargs.setdefault("checks", PASSING)
    with psycopg.connect(SOURCE_URL) as source, psycopg.connect(TARGET_URL) as target:
        return restore(source, target, **kwargs)


def test_everything_is_copied(empty_target: None) -> None:
    result = _restore()

    source, target = _counts(SOURCE_URL), _counts(TARGET_URL)
    assert target == source
    assert sum(source.values()) > 0
    assert {t.table for t in result.tables} == set(source)
    assert not EXCLUDED_TABLES & set(source)
    assert result.checks_passed == 1
    with psycopg.connect(SOURCE_URL) as conn:
        # Upserts use up sequence values, so the source's position can be past
        # its highest id; the restore carries the position over as it is.
        position = conn.execute(
            "SELECT last_value FROM pg_sequences WHERE sequencename = 'status_status_id_seq'"
        ).fetchone()[0]
    with psycopg.connect(TARGET_URL) as conn:
        assert conn.execute("SELECT count(*) FROM feedback").fetchone()[0] == 0
        top = conn.execute("SELECT max(status_id) FROM status").fetchone()[0]
        conn.execute("INSERT INTO status (status) VALUES ('Restored test')")
        new = conn.execute(
            "SELECT status_id FROM status WHERE status = 'Restored test'"
        ).fetchone()[0]
        conn.rollback()
    assert new == position + 1  # continues where the source is, never reusing an id
    assert new > top
    assert result.sequences >= 1


def test_existing_data_is_refused_unless_replaced(empty_target: None) -> None:
    _restore()
    with pytest.raises(RestoreError, match="already has data.*--replace"):
        _restore()
    result = _restore(replace=True)
    assert _counts(TARGET_URL) == _counts(SOURCE_URL)
    assert result.tables


def test_failing_checks_roll_everything_back(empty_target: None) -> None:
    with pytest.raises(RestoreError, match="1 sanity checks failed"):
        _restore(checks=FAILING)
    assert set(_counts(TARGET_URL).values()) == {0}


def test_the_size_guard_rolls_back(empty_target: None) -> None:
    with pytest.raises(SizeLimitError):
        _restore(guard=SizeGuard(warn_bytes=1, refuse_bytes=1))
    assert set(_counts(TARGET_URL).values()) == {0}


def test_the_size_is_checked_again_after_copying(empty_target: None) -> None:
    """A target under the limit before the copy but over it after: rolled back."""
    with psycopg.connect(TARGET_URL) as conn:
        before = database_size(conn)
    with pytest.raises(SizeLimitError, match="before committing"):
        _restore(guard=SizeGuard(warn_bytes=before + 1, refuse_bytes=before + 1))
    assert set(_counts(TARGET_URL).values()) == {0}


def test_a_short_copy_is_caught(
    empty_target: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = restore_module._copy_table

    def drops_races(source, target, table, cols):  # noqa: ANN001, ANN202
        if table != "races":
            real(source, target, table, cols)

    monkeypatch.setattr(restore_module, "_copy_table", drops_races)
    with pytest.raises(RestoreError, match="races: copied 0 rows"):
        _restore()
    assert set(_counts(TARGET_URL).values()) == {0}


def test_a_target_without_the_schema_is_refused() -> None:
    blank = TARGET_DB + "_blank"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{blank}"')
        admin.execute(f'CREATE DATABASE "{blank}"')
    try:
        url = urlunsplit(_parts._replace(path=f"/{blank}"))
        with (
            psycopg.connect(SOURCE_URL) as source,
            psycopg.connect(url) as target,
            pytest.raises(RestoreError, match="alembic upgrade head"),
        ):
            restore(source, target, checks=PASSING)
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{blank}" WITH (FORCE)')


def test_a_different_revision_is_refused(empty_target: None) -> None:
    with psycopg.connect(TARGET_URL) as conn:
        real = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        conn.execute("UPDATE alembic_version SET version_num = '0001'")
        conn.commit()
    try:
        with pytest.raises(RestoreError, match="revisions differ"):
            _restore()
    finally:
        with psycopg.connect(TARGET_URL) as conn:
            conn.execute("UPDATE alembic_version SET version_num = %s", (real,))
            conn.commit()
