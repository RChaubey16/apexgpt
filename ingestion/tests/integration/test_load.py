"""Loader integration tests against a real Postgres + pgvector database.

Skipped unless TEST_DATABASE_URL is set. The schema comes from the backend's
Alembic migrations (run here via `uv run alembic upgrade head` in backend/).

WARNING: these tests TRUNCATE the F1 tables. Never point TEST_DATABASE_URL at a
database holding real data.
"""

import dataclasses
import os
import subprocess
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from structured import __main__ as cli
from structured.config import REPO_ROOT, Settings, normalise_database_url
from structured.load import TableReport, load
from structured.transform import F1Data, transform
from tests.fixture_dump import FakeSource, tables, write_zip

pytestmark = pytest.mark.integration

_RAW_URL = os.environ.get("TEST_DATABASE_URL")
if not _RAW_URL:
    pytest.skip("TEST_DATABASE_URL not set", allow_module_level=True)

DATABASE_URL = normalise_database_url(_RAW_URL)
F1_TABLES = (
    "seasons",
    "circuits",
    "drivers",
    "constructors",
    "status",
    "races",
    "results",
    "sprint_results",
    "qualifying",
    "driver_standings",
    "constructor_standings",
    "pit_stops",
)


@pytest.fixture(scope="module", autouse=True)
def migrated() -> None:
    subprocess.run(  # noqa: S603
        ["uv", "run", "--frozen", "alembic", "upgrade", "head"],  # noqa: S607
        cwd=REPO_ROOT / "backend",
        env={**os.environ, "DATABASE_URL": DATABASE_URL},
        check=True,
        capture_output=True,
    )


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute(f"TRUNCATE {', '.join(F1_TABLES)} RESTART IDENTITY CASCADE")
        yield connection


def _counts(conn: psycopg.Connection) -> dict[str, int]:
    return {
        t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]  # noqa: S608
        for t in F1_TABLES
    }


def _load(conn: psycopg.Connection, data: F1Data, first: int = 1950, last: int = 2025):
    return load(conn, data, first, last)


def _changes(reports: dict[str, TableReport]) -> dict[str, tuple[int, int, int]]:
    return {
        name: (r.inserted, r.updated, r.deleted)
        for name, r in reports.items()
        if (r.inserted, r.updated, r.deleted) != (0, 0, 0)
    }


def test_first_load_inserts_everything(conn: psycopg.Connection) -> None:
    data = transform(FakeSource())

    reports = _load(conn, data)

    assert _counts(conn) == data.counts()
    assert all(r.inserted == data.counts()[name] for name, r in reports.items())


def test_reload_is_a_no_op(conn: psycopg.Connection) -> None:
    _load(conn, transform(FakeSource()))
    before = _counts(conn)

    reports = _load(conn, transform(FakeSource()))

    assert _changes(reports) == {}
    assert _counts(conn) == before


def test_values_round_trip(conn: psycopg.Connection) -> None:
    _load(conn, transform(FakeSource()))

    row = conn.execute(
        "SELECT d.ref, r.position, r.points, r.time_ms, s.status, r.fastest_lap_ms "
        "FROM results r JOIN drivers d USING (driver_id) JOIN status s USING (status_id) "
        "WHERE r.result_id = 100"
    ).fetchone()
    assert row == ("max_verstappen", 1, Decimal("25.00"), 5_523_897, "Finished", 92_090)
    retired = conn.execute(
        "SELECT r.position, s.status FROM results r JOIN status s USING (status_id) "
        "WHERE r.result_id = 101"
    ).fetchone()
    assert retired == (None, "Retired")


def test_changed_and_removed_rows_are_synced(conn: psycopg.Connection) -> None:
    _load(conn, transform(FakeSource()))

    changed = tables()
    # A corrected result, a removed pit stop and a race removed from the dump.
    next(r for r in changed["sessionentry"] if r["id"] == "142").update(points="2")
    changed["pitstop"] = []
    next(r for r in changed["round"] if r["id"] == "4").update(is_cancelled="t")
    reports = _load(conn, transform(FakeSource(changed)))

    changes = _changes(reports)
    assert changes["races"] == (0, 0, 1)
    assert changes["pit_stops"] == (0, 0, 1)
    # Round 4's results/qualifying/standings went with the race (ON DELETE CASCADE).
    assert conn.execute(
        "SELECT count(*) FROM results WHERE race_id = 4"
    ).fetchone() == (0,)
    assert conn.execute(
        "SELECT count(*) FROM qualifying WHERE race_id = 4"
    ).fetchone() == (0,)
    # Entities are never deleted, even when no longer referenced.
    assert conn.execute("SELECT count(*) FROM circuits").fetchone() == (2,)


def test_updates_touch_only_changed_rows(conn: psycopg.Connection) -> None:
    _load(conn, transform(FakeSource()))

    changed = tables()
    next(r for r in changed["sessionentry"] if r["id"] == "100").update(points="26")
    next(r for r in changed["driver"] if r["id"] == "1").update(nationality="English")
    reports = _load(conn, transform(FakeSource(changed)))

    assert _changes(reports) == {"results": (0, 1, 0), "drivers": (0, 1, 0)}
    assert conn.execute(
        "SELECT points FROM results WHERE result_id = 100"
    ).fetchone() == (Decimal("26.00"),)


def test_rows_outside_the_season_range_are_untouched(conn: psycopg.Connection) -> None:
    _load(conn, transform(FakeSource()))

    # Loading only 2021 must not delete the 2020 race.
    reports = _load(conn, transform(FakeSource(), 2021, 2021), 2021, 2021)

    assert _changes(reports) == {}
    assert conn.execute(
        "SELECT count(*) FROM races WHERE season = 2020"
    ).fetchone() == (1,)


def test_failed_load_rolls_back_completely(conn: psycopg.Connection) -> None:
    _load(conn, transform(FakeSource()))
    before = _counts(conn)

    data = transform(FakeSource())
    data.drivers[0] = {**data.drivers[0], "nationality": "changed"}
    data.results = [*data.results, {**data.results[0], "result_id": 999, "grid": -1}]
    with pytest.raises(psycopg.errors.CheckViolation):
        _load(conn, data)

    assert _counts(conn) == before
    assert conn.execute(
        "SELECT nationality FROM drivers WHERE driver_id = 1"
    ).fetchone() == ("British",)


def test_status_ids_are_reused_across_loads(conn: psycopg.Connection) -> None:
    _load(conn, transform(FakeSource()))
    ids = dict(conn.execute("SELECT status, status_id FROM status").fetchall())

    data = transform(FakeSource())
    _load(conn, dataclasses.replace(data, statuses=[*data.statuses, "Engine"]))

    after = dict(conn.execute("SELECT status, status_id FROM status").fetchall())
    assert {k: after[k] for k in ids} == ids
    assert "Engine" in after


def test_cli_end_to_end(
    conn: psycopg.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    dump = write_zip(tmp_path / "dump.zip")

    assert cli.run(["--dump", str(dump)]) == 0
    assert _counts(conn)["results"] == 5
