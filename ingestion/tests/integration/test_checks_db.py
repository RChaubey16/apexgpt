"""Sanity checks against a real Postgres (see test_load.py for setup notes).

The real facts (Hamilton 105 wins, ...) need the real dump; they run in the
data-checks workflow. Here: the machinery (applicability, pre-commit rollback,
CLI) and that every real check's SQL is valid against the schema.
"""

import os
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from structured import __main__ as cli
from structured import checks as checks_module
from structured.checks import CHECKS, Check, DataCheckError, run_checks
from structured.config import Settings, normalise_database_url
from structured.load import load
from structured.transform import transform
from tests.fixture_dump import FakeSource, write_zip
from tests.integration.test_load import F1_TABLES, migrated  # noqa: F401  (fixture)

pytestmark = pytest.mark.integration

_RAW_URL = os.environ.get("TEST_DATABASE_URL")
if not _RAW_URL:
    pytest.skip("TEST_DATABASE_URL not set", allow_module_level=True)
DATABASE_URL = normalise_database_url(_RAW_URL)

# Facts about the fixture dump (seasons 2020 and 2021 loaded).
FIXTURE_PASS = Check("2021 R1 winner", "SELECT driver_ref FROM v_race_winners "
                     "WHERE season = 2021", "max_verstappen", (2021, 2021))  # fmt: skip
FIXTURE_FAIL = Check("Wrong count", "SELECT count(*) FROM races", 99)
NOT_LOADED = Check("1950 fact", "SELECT 1/0", 1, (1950, 1950))  # would error if run


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute(f"TRUNCATE {', '.join(F1_TABLES)} RESTART IDENTITY CASCADE")
        yield connection


def _load(conn: psycopg.Connection, checks: list[Check]) -> None:
    load(conn, transform(FakeSource()), 1950, 2025, checks=checks)


def _races(conn: psycopg.Connection) -> int:
    return conn.execute("SELECT count(*) FROM races").fetchone()[0]


def test_passing_checks_commit_the_load(conn: psycopg.Connection) -> None:
    _load(conn, [FIXTURE_PASS, NOT_LOADED])

    assert _races(conn) == 2


def test_a_failing_check_rolls_back_the_whole_load(conn: psycopg.Connection) -> None:
    with pytest.raises(DataCheckError, match="Wrong count: 2"):
        _load(conn, [FIXTURE_PASS, FIXTURE_FAIL])

    assert _races(conn) == 0


def test_checks_see_the_new_data_before_commit(conn: psycopg.Connection) -> None:
    """Checks run inside the load transaction, against the data being loaded."""
    _load(conn, [Check("Races so far", "SELECT count(*) FROM races", 2)])


def test_checks_for_seasons_not_loaded_are_skipped(conn: psycopg.Connection) -> None:
    _load(conn, [])
    with conn.cursor() as cur:
        results = run_checks(cur, [FIXTURE_PASS, NOT_LOADED])

    assert [(r.passed, r.skipped) for r in results] == [(True, False), (False, True)]


def test_every_real_check_runs_against_the_schema(conn: psycopg.Connection) -> None:
    """Valid SQL with the expected type, even though the fixture's facts differ."""
    _load(conn, [])
    all_seasons = [
        Check(c.name, c.sql, c.expected, None, c.comparison, c.needs_seeds)
        for c in CHECKS
    ]
    with conn.cursor() as cur:
        results = run_checks(cur, all_seasons)

    for result in results:
        assert not result.skipped
        if result.actual is not None:
            expected_type = type(result.check.expected)
            numeric = (int, Decimal)
            if isinstance(result.check.expected, numeric):
                assert isinstance(result.actual, numeric), result.check.name
            else:
                assert isinstance(result.actual, expected_type), result.check.name


def test_integrity_checks_pass_on_consistent_data(conn: psycopg.Connection) -> None:
    _load(conn, [])
    integrity = [
        c
        for c in CHECKS
        if c.seasons is None and not c.needs_seeds and "champion" not in c.name
    ]
    with conn.cursor() as cur:
        results = run_checks(cur, integrity, seeds_synced=False)

    assert all(r.passed for r in results), [r.describe() for r in results]


# --- CLIs ---


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)


def test_loader_cli_fails_and_rolls_back_when_checks_fail(
    conn: psycopg.Connection,
    env: None,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    dump = write_zip(tmp_path / "dump.zip")

    # The real facts don't hold for the tiny fixture (e.g. 2021 champion's points).
    assert cli.run(["--dump", str(dump), "--no-seeds"]) == 1
    assert "data check(s) failed" in caplog.text
    assert _races(conn) == 0

    assert cli.run(["--dump", str(dump), "--no-seeds", "--no-checks"]) == 0
    assert _races(conn) == 2


def test_standalone_checks_cli(
    conn: psycopg.Connection,
    env: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert checks_module.main([]) == 1  # nothing loaded yet

    _load(conn, [])
    monkeypatch.setattr(checks_module, "CHECKS", (FIXTURE_PASS, NOT_LOADED))
    assert checks_module.main([]) == 0
    out = capsys.readouterr().out
    assert "PASS  2021 R1 winner" in out
    assert "1/1 passed, 1 skipped" in out

    monkeypatch.setattr(checks_module, "CHECKS", (FIXTURE_FAIL,))
    assert checks_module.main([]) == 1
