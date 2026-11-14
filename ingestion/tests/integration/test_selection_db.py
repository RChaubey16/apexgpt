"""Article selection against a real Postgres (see test_load.py for setup notes)."""

import os
from collections.abc import Iterator

import psycopg
import pytest

from narrative.entities import read_entity_rows
from narrative.selection import Depth, Kind, select_articles
from narrative.topics import Group, Topic
from structured.config import normalise_database_url
from structured.load import load
from structured.transform import transform
from tests.fixture_dump import FakeSource
from tests.integration.test_load import F1_TABLES, migrated  # noqa: F401  (fixture)

pytestmark = pytest.mark.integration

_RAW_URL = os.environ.get("TEST_DATABASE_URL")
if not _RAW_URL:
    pytest.skip("TEST_DATABASE_URL not set", allow_module_level=True)
DATABASE_URL = normalise_database_url(_RAW_URL)


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute(f"TRUNCATE {', '.join(F1_TABLES)} RESTART IDENTITY CASCADE")
        load(connection, transform(FakeSource()), 1950, 2025)
        yield connection


def test_entity_rows_come_from_the_structured_data(conn: psycopg.Connection) -> None:
    rows = read_entity_rows(conn)

    assert [s.year for s in rows.seasons] == [2020, 2021]
    assert {r.name for r in rows.races} == {"Bahrain Grand Prix", "Austrian Grand Prix"}
    drivers = {d.name: d for d in rows.drivers}
    assert set(drivers) == {"Lewis Hamilton", "Max Verstappen"}
    # Career numbers come from the stats view: the 2020 shared drive is one win
    # (counted once), and his unclassified 2021 "P2" is not a podium.
    assert (drivers["Lewis Hamilton"].wins, drivers["Lewis Hamilton"].podiums) == (1, 1)
    assert drivers["Max Verstappen"].wins == 2
    teams = {t.name: t for t in rows.constructors}
    assert teams["Red Bull"].champion is True  # 2021 constructors' champion
    assert teams["Mercedes"].champion is False
    assert teams["Red Bull"].seasons == frozenset({2020, 2021})
    assert teams["Mercedes"].seasons == frozenset({2020, 2021})
    assert rows.driver_refs == {"hamilton": 1, "max_verstappen": 2}
    assert set(rows.circuit_refs) == {"bahrain", "red_bull_ring"}


def test_select_articles_from_the_database(conn: psycopg.Connection) -> None:
    rows = read_entity_rows(conn)
    topics = [
        Topic(
            title="Hamilton–Verstappen rivalry",
            group=Group.RIVALRY,
            drivers=("hamilton", "max_verstappen"),
            constructors=("mercedes", "red_bull"),
            season=2021,
            circuit="bahrain",
        )
    ]

    selection = select_articles(rows, topics)

    got = {a.title: a for a in selection.articles}
    assert {t: (a.kinds, a.depth) for t, a in got.items()} == {
        "2020 Formula One World Championship": ((Kind.SEASON,), Depth.FULL),
        "2021 Formula One World Championship": ((Kind.SEASON,), Depth.FULL),
        "2021 Bahrain Grand Prix": ((Kind.RACE,), Depth.RACE),
        "Bahrain International Circuit": ((Kind.CIRCUIT,), Depth.CIRCUIT),
        "Lewis Hamilton": ((Kind.DRIVER,), Depth.FULL),
        "Max Verstappen": ((Kind.DRIVER,), Depth.FULL),
        "Mercedes-Benz in Formula One": ((Kind.CONSTRUCTOR,), Depth.FULL),
        "Red Bull Racing": ((Kind.CONSTRUCTOR,), Depth.FULL),
        "Hamilton–Verstappen rivalry": ((Kind.TOPIC,), Depth.FULL),
    }
    rivalry = got["Hamilton–Verstappen rivalry"]
    ids = {r.name: r.circuit_id for r in rows.circuits}
    assert rivalry.circuit_id == ids["Bahrain International Circuit"]
    assert rivalry.driver_ids == (1, 2)
    race = got["2021 Bahrain Grand Prix"]
    assert race.season == 2021
    assert race.circuit_id == ids["Bahrain International Circuit"]
    # Entities without a Wikipedia URL in the source are reported, not guessed.
    assert {s.source.split(" (")[0] for s in selection.skipped} == {
        f"race {next(r.race_id for r in rows.races if r.name == 'Austrian Grand Prix')}",
        f"circuit {ids['Red Bull Ring']}",
    }
