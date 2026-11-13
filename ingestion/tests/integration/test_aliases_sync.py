"""Alias and lineage sync against a real Postgres (see test_load.py for setup notes)."""

import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from structured import __main__ as cli
from structured.aliases import Seeds, read_seeds
from structured.config import Settings, normalise_database_url
from structured.errors import SeedError
from structured.load import load
from structured.transform import transform
from tests.fixture_dump import FakeSource, write_zip
from tests.integration.test_load import F1_TABLES, migrated  # noqa: F401  (fixture)

pytestmark = pytest.mark.integration

_RAW_URL = os.environ.get("TEST_DATABASE_URL")
if not _RAW_URL:
    pytest.skip("TEST_DATABASE_URL not set", allow_module_level=True)
DATABASE_URL = normalise_database_url(_RAW_URL)

# The fixture dump's drivers: hamilton (1), max_verstappen (2); constructors:
# mercedes (1), red_bull (2). Both teams raced in 2020 and 2021.
LINEAGE_OK = "predecessor,successor,season,note\nmercedes,red_bull,2021,Test edge\n"


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute(f"TRUNCATE {', '.join(F1_TABLES)} RESTART IDENTITY CASCADE")
        yield connection


def _seeds(
    tmp_path: Path,
    drivers: str = "ref,alias\nhamilton,Lewis\nmax_verstappen,Max\nhamilton,Champ\nmax_verstappen,Champ\n",
    constructors: str = "ref,alias\nmercedes,Silver Arrows\nred_bull,RBR\n",
    lineage: str = LINEAGE_OK,
) -> Seeds:
    (tmp_path / "driver_aliases.csv").write_text(drivers)
    (tmp_path / "constructor_aliases.csv").write_text(constructors)
    (tmp_path / "constructor_lineage.csv").write_text(lineage)
    return read_seeds(tmp_path)


def _load(conn: psycopg.Connection, seeds: Seeds):
    return load(conn, transform(FakeSource()), 1950, 2025, seeds)


def _aliases(conn: psycopg.Connection, table: str, id_column: str) -> set[tuple]:
    query = sql.SQL("SELECT alias, {}, kind FROM {}").format(
        sql.Identifier(id_column), sql.Identifier(table)
    )
    return set(conn.execute(query).fetchall())


def test_generated_and_curated_aliases(
    conn: psycopg.Connection, tmp_path: Path
) -> None:
    _load(conn, _seeds(tmp_path))

    assert _aliases(conn, "driver_aliases", "driver_id") == {
        ("lewis hamilton", 1, "name"),
        ("hamilton", 1, "surname"),
        ("max verstappen", 2, "name"),
        ("verstappen", 2, "surname"),
        ("lewis", 1, "nickname"),
        ("max", 2, "nickname"),
        # One alias, two drivers: resolution (F3.4) chooses.
        ("champ", 1, "nickname"),
        ("champ", 2, "nickname"),
    }
    assert _aliases(conn, "constructor_aliases", "constructor_id") == {
        ("mercedes", 1, "name"),
        # Name "Red Bull" and ref "red_bull" normalise to the same alias.
        ("red bull", 2, "name"),
        ("silver arrows", 1, "nickname"),
        ("rbr", 2, "nickname"),
    }
    assert conn.execute(
        "SELECT predecessor_id, successor_id, season, note FROM constructor_lineage"
    ).fetchall() == [(1, 2, 2021, "Test edge")]


def test_curated_alias_equal_to_a_generated_one_keeps_the_generated_kind(
    conn: psycopg.Connection, tmp_path: Path
) -> None:
    _load(conn, _seeds(tmp_path, drivers="ref,alias\nhamilton,Hamilton\n"))

    assert ("hamilton", 1, "surname") in _aliases(conn, "driver_aliases", "driver_id")


def test_resync_is_a_no_op(conn: psycopg.Connection, tmp_path: Path) -> None:
    seeds = _seeds(tmp_path)
    _load(conn, seeds)

    reports = _load(conn, seeds)

    for table in ("driver_aliases", "constructor_aliases", "constructor_lineage"):
        assert (
            reports[table].inserted,
            reports[table].updated,
            reports[table].deleted,
        ) == (
            0,
            0,
            0,
        )


def test_seed_edits_are_synced(conn: psycopg.Connection, tmp_path: Path) -> None:
    _load(conn, _seeds(tmp_path))

    edited = _seeds(
        tmp_path,
        drivers="ref,alias\nhamilton,Lewis\nhamilton,Sir Lewis\n",
        lineage="predecessor,successor,season,note\nmercedes,red_bull,2021,Changed note\n",
    )
    reports = _load(conn, edited)

    drivers = reports["driver_aliases"]
    # Added "sir lewis"; removed "max" and both "champ" rows.
    assert (drivers.inserted, drivers.updated, drivers.deleted) == (1, 0, 3)
    assert reports["constructor_lineage"].updated == 1
    assert conn.execute("SELECT note FROM constructor_lineage").fetchone() == (
        "Changed note",
    )


def test_unknown_ref_fails_and_rolls_back(
    conn: psycopg.Connection, tmp_path: Path
) -> None:
    seeds = _seeds(tmp_path, drivers="ref,alias\nsenna,Magic\n")

    with pytest.raises(SeedError, match="unknown driver 'senna'"):
        _load(conn, seeds)

    # Same transaction as the data load: nothing was written.
    assert conn.execute("SELECT count(*) FROM results").fetchone() == (0,)


@pytest.mark.parametrize(
    ("lineage", "message"),
    [
        ("mercedes,red_bull,2025,", "red_bull did not race in 2025"),
        ("mercedes,red_bull,2023,", "mercedes did not race in 2022 or 2023"),
        ("brawn,red_bull,2021,", "unknown constructor 'brawn'"),
    ],
)
def test_lineage_must_match_the_race_data(
    conn: psycopg.Connection, tmp_path: Path, lineage: str, message: str
) -> None:
    seeds = _seeds(tmp_path, lineage=f"predecessor,successor,season,note\n{lineage}\n")

    with pytest.raises(SeedError, match=message):
        _load(conn, seeds)


def test_cli_reports_seed_problems_and_supports_no_seeds(
    conn: psycopg.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    dump = write_zip(tmp_path / "dump.zip")

    # The real seeds reference drivers the tiny fixture doesn't have.
    assert cli.run(["--dump", str(dump)]) == 1
    assert "--no-seeds" in caplog.text
    assert conn.execute("SELECT count(*) FROM results").fetchone() == (0,)

    assert cli.run(["--dump", str(dump), "--no-seeds"]) == 0
    assert conn.execute("SELECT count(*) FROM driver_aliases").fetchone() == (0,)
