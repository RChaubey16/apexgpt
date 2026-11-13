"""Integration tests for the stats views (migration 0004) on a small, hand-built
dataset that exercises each rule: shared drives, poles from the grid, fastest laps
only from 2004, non-starts, champions from the last race, teammate comparisons.

Skipped unless TEST_DATABASE_URL is set (see test_database.py for the warning).
"""

import datetime as dt
import os
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.orm import Session

from app.core.config import normalise_database_url
from app.db.models import (
    Circuit,
    Constructor,
    ConstructorStanding,
    Driver,
    DriverStanding,
    Qualifying,
    Race,
    Result,
    Season,
    SprintResult,
    Status,
)

pytestmark = pytest.mark.integration

_RAW_URL = os.environ.get("TEST_DATABASE_URL")
if not _RAW_URL:
    pytest.skip("TEST_DATABASE_URL not set", allow_module_level=True)

DATABASE_URL = normalise_database_url(_RAW_URL)
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
VIEWS = (
    "v_race_winners",
    "v_driver_career",
    "v_season_summary",
    "v_head_to_head_teammates",
)

# Drivers: 1 = Ann (A), 2 = Bob (B), 3 = Cat (C). Constructors: 1 = Xteam, 2 = Yteam.
# Races: 1 = 2020 R1, 2 = 2020 R2, 3 = 2021 R1, 4 = 1955 R1.


def _alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.attributes["database_url"] = DATABASE_URL
    return cfg


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    eng = create_engine(DATABASE_URL, connect_args={"prepare_threshold": None})
    command.upgrade(_alembic_config(), "head")
    yield eng
    command.downgrade(_alembic_config(), "base")
    eng.dispose()


@pytest.fixture(scope="module")
def session(engine: Engine) -> Iterator[Session]:
    """Loads the dataset once; everything is rolled back at the end."""
    with engine.connect() as conn:
        trans = conn.begin()
        with Session(bind=conn, join_transaction_mode="create_savepoint") as s:
            _load_dataset(s)
            yield s
        trans.rollback()


def _load_dataset(s: Session) -> None:
    s.add_all(
        [Season(year=y, wikipedia_url=f"https://w/{y}") for y in (1955, 2020, 2021)]
        + [Circuit(circuit_id=1, ref="track", name="Track")]
        + [
            Driver(
                driver_id=1, ref="ann", forename="Ann", surname="A", nationality="X"
            ),
            Driver(driver_id=2, ref="bob", forename="Bob", surname="B"),
            Driver(driver_id=3, ref="cat", forename="Cat", surname="C"),
            Constructor(constructor_id=1, ref="xteam", name="Xteam"),
            Constructor(constructor_id=2, ref="yteam", name="Yteam"),
        ]
        + [Status(status=t) for t in ("Finished", "Engine", "Withdrew")]
    )
    s.flush()
    status = dict(s.execute(select(Status.status, Status.status_id)).all())
    s.add_all(
        [
            Race(
                race_id=1,
                season=2020,
                round=1,
                name="First GP",
                circuit_id=1,
                date=dt.date(2020, 3, 1),
                wikipedia_url="https://w/r1",
            ),
            Race(
                race_id=2,
                season=2020,
                round=2,
                name="Second GP",
                circuit_id=1,
                date=dt.date(2020, 4, 1),
            ),
            Race(
                race_id=3,
                season=2021,
                round=1,
                name="Third GP",
                circuit_id=1,
                date=dt.date(2021, 3, 1),
            ),
            Race(
                race_id=4,
                season=1955,
                round=1,
                name="Old GP",
                circuit_id=1,
                date=dt.date(1955, 5, 1),
            ),
        ]
    )
    s.flush()

    n = iter(range(1, 100))

    def result(
        race: int,
        driver: int,
        team: int,
        pos: int | None,
        order: int,
        grid: int,
        points: str,
        st: str = "Finished",
        laps: int = 50,
        **extra: Any,
    ) -> Result:
        return Result(
            result_id=next(n),
            race_id=race,
            driver_id=driver,
            constructor_id=team,
            position=pos,
            position_order=order,
            grid=grid,
            points=Decimal(points),
            laps=laps,
            status_id=status[st],
            **extra,
        )

    s.add_all(
        [
            # 2020 R1: Ann wins from pole with the fastest lap; Cat's engine fails.
            result(1, 1, 1, 1, 1, 1, "25", time_ms=5_523_897, fastest_lap_rank=1),
            result(1, 2, 1, 2, 2, 2, "18"),
            result(1, 3, 2, None, 3, 3, "0", st="Engine", laps=10),
            # 2020 R2: Bob wins; Ann starts on pole, finishes 3rd; Cat withdrew.
            result(2, 2, 1, 1, 1, 2, "25"),
            result(2, 1, 1, 3, 2, 1, "15"),
            result(2, 3, 2, None, 3, 0, "0", st="Withdrew", laps=0),
            # 2021 R1: Ann (now Yteam) wins, Cat (now Xteam) 2nd.
            result(3, 1, 2, 1, 1, 2, "25"),
            result(3, 3, 1, 2, 2, 1, "18"),
            # 1955: Ann shares Cat's winning Yteam car (points split) and also
            # drives an Xteam car; fastest lap before 2004 is not counted.
            result(4, 3, 2, 1, 1, 3, "4"),
            result(4, 1, 2, 1, 1, 3, "4", fastest_lap_rank=1),
            result(4, 1, 1, 4, 4, 5, "0"),
            SprintResult(
                sprint_result_id=1,
                race_id=3,
                driver_id=1,
                constructor_id=2,
                grid=1,
                position=1,
                position_order=1,
                points=Decimal("8"),
                laps=17,
                status_id=status["Finished"],
            ),
            # Qualifying (R2 only): Bob out-qualified Ann, though Ann started on pole.
            Qualifying(race_id=2, driver_id=2, constructor_id=1, position=1),
            Qualifying(race_id=2, driver_id=1, constructor_id=1, position=2),
            # Standings: 2020 after R1 (not final) and after R2 (final); 2021 final.
            DriverStanding(race_id=1, driver_id=1, points=25, position=1, wins=1),
            DriverStanding(race_id=1, driver_id=2, points=18, position=2, wins=0),
            DriverStanding(race_id=2, driver_id=2, points=43, position=1, wins=1),
            DriverStanding(race_id=2, driver_id=1, points=40, position=2, wins=1),
            DriverStanding(race_id=3, driver_id=1, points=33, position=1, wins=1),
            DriverStanding(race_id=3, driver_id=3, points=18, position=2, wins=0),
            ConstructorStanding(
                race_id=2, constructor_id=1, points=83, position=1, wins=2
            ),
        ]
    )
    s.flush()


def _rows(session: Session, sql: str, **params: object) -> list[dict[str, Any]]:
    return [dict(r._mapping) for r in session.execute(text(sql), params)]


def _one(session: Session, sql: str, **params: object) -> dict[str, Any]:
    rows = _rows(session, sql, **params)
    assert len(rows) == 1, rows
    return rows[0]


# --- v_race_winners ---


def test_race_winners(session: Session) -> None:
    rows = _rows(
        session,
        "SELECT season, round, driver_ref, constructor_ref, race_time "
        "FROM v_race_winners ORDER BY season, round, driver_ref",
    )

    assert [(r["season"], r["driver_ref"], r["constructor_ref"]) for r in rows] == [
        (1955, "ann", "yteam"),
        (1955, "cat", "yteam"),  # shared drive: both drivers credited
        (2020, "ann", "xteam"),
        (2020, "bob", "xteam"),
        (2021, "ann", "yteam"),
    ]
    assert rows[2]["race_time"] == "1:32:03.897"
    assert rows[3]["race_time"] is None


def test_race_winners_include_names_and_citation(session: Session) -> None:
    row = _one(session, "SELECT * FROM v_race_winners WHERE race_id = 1")

    assert row["race_name"] == "First GP"
    assert row["driver_name"] == "Ann A"
    assert row["circuit_name"] == "Track"
    assert row["wikipedia_url"] == "https://w/r1"


# --- v_driver_career ---


def test_driver_career(session: Session) -> None:
    ann = _one(session, "SELECT * FROM v_driver_career WHERE driver_ref = 'ann'")

    assert {
        k: ann[k]
        for k in (
            "first_season",
            "last_season",
            "seasons",
            "race_entries",
            "race_starts",
            "wins",
            "podiums",
            "poles",
            "fastest_laps_since_2004",
            "dnfs",
            "championships",
            "best_championship_position",
            "sprint_entries",
            "sprint_wins",
        )
    } == {
        "first_season": 1955,
        "last_season": 2021,
        "seasons": 3,
        "race_entries": 4,
        "race_starts": 4,
        "wins": 3,  # the shared 1955 win counts once, despite two cars
        "podiums": 4,
        "poles": 2,  # grid = 1 in R1 and R2
        "fastest_laps_since_2004": 1,  # the 1955 fastest lap is excluded
        "dnfs": 0,
        "championships": 1,  # 2021; second in 2020
        "best_championship_position": 1,
        "sprint_entries": 1,
        "sprint_wins": 1,
    }
    assert ann["race_points"] == Decimal("69.00")
    assert ann["sprint_points"] == Decimal("8.00")
    assert ann["total_points"] == Decimal("77.00")
    assert ann["teams"] == "Xteam, Yteam"


def test_non_starts_and_dnfs(session: Session) -> None:
    cat = _one(session, "SELECT * FROM v_driver_career WHERE driver_ref = 'cat'")

    assert (cat["race_entries"], cat["race_starts"]) == (4, 3)  # withdrew from R2
    assert cat["dnfs"] == 1  # R1 engine failure; the withdrawal is not a DNF
    assert cat["wins"] == 1
    assert cat["championships"] == 0
    assert cat["best_championship_position"] == 2


def test_champion_counts_only_final_standings(session: Session) -> None:
    """Ann led after 2020 R1 but Bob won the 2020 title."""
    bob = _one(session, "SELECT * FROM v_driver_career WHERE driver_ref = 'bob'")

    assert bob["championships"] == 1


# --- v_season_summary ---


def test_season_summary(session: Session) -> None:
    rows = {
        r["season"]: r
        for r in _rows(session, "SELECT * FROM v_season_summary ORDER BY season")
    }

    s2020 = rows[2020]
    assert (s2020["races"], s2020["first_race_date"], s2020["last_race_date"]) == (
        2,
        dt.date(2020, 3, 1),
        dt.date(2020, 4, 1),
    )
    assert (
        s2020["champion_ref"],
        s2020["champion_points"],
        s2020["champion_wins"],
    ) == (
        "bob",
        Decimal("43.00"),
        1,
    )
    assert (s2020["runner_up_ref"], s2020["title_margin"]) == ("ann", Decimal("3.00"))
    assert s2020["champion_teams"] == "Xteam"
    assert s2020["constructors_champion_ref"] == "xteam"
    assert s2020["distinct_race_winners"] == 2
    assert s2020["wikipedia_url"] == "https://w/2020"

    # No constructors' standings in 2021 -> no constructors' champion.
    assert rows[2021]["champion_teams"] == "Yteam"
    assert rows[2021]["constructors_champion_ref"] is None
    # No standings at all (1955 here) -> the season is still listed.
    assert rows[1955]["champion_ref"] is None
    assert rows[1955]["distinct_race_winners"] == 2


# --- v_head_to_head_teammates ---


def test_head_to_head_both_directions(session: Session) -> None:
    sql = (
        "SELECT * FROM v_head_to_head_teammates "
        "WHERE season = 2020 AND driver_ref = :a AND teammate_ref = :b"
    )
    ann = _one(session, sql, a="ann", b="bob")
    bob = _one(session, sql, a="bob", b="ann")

    assert ann["constructor_ref"] == "xteam"
    assert ann["races_together"] == 2
    # R1 by grid (no qualifying data), R2 by qualifying (Bob ahead despite Ann's pole).
    assert (ann["qualified_ahead"], ann["qualified_behind"]) == (1, 1)
    assert (ann["finished_ahead"], ann["finished_behind"]) == (1, 1)
    assert (ann["wins"], ann["teammate_wins"]) == (1, 1)
    assert (ann["points"], ann["teammate_points"]) == (
        Decimal("40.00"),
        Decimal("43.00"),
    )
    assert (bob["points"], bob["teammate_points"]) == (
        ann["teammate_points"],
        ann["points"],
    )


def test_head_to_head_only_counts_races_together_in_the_same_team(
    session: Session,
) -> None:
    rows = _rows(
        session,
        "SELECT season, constructor_ref, driver_ref, teammate_ref, races_together "
        "FROM v_head_to_head_teammates ORDER BY season, constructor_ref, driver_ref",
    )

    # 2021: Ann (Yteam) and Cat (Xteam) were not teammates. 1955: Ann and Cat
    # shared Yteam; Ann's other car (Xteam) had no teammate.
    assert rows == [
        {
            "season": 1955,
            "constructor_ref": "yteam",
            "driver_ref": "ann",
            "teammate_ref": "cat",
            "races_together": 1,
        },
        {
            "season": 1955,
            "constructor_ref": "yteam",
            "driver_ref": "cat",
            "teammate_ref": "ann",
            "races_together": 1,
        },
        {
            "season": 2020,
            "constructor_ref": "xteam",
            "driver_ref": "ann",
            "teammate_ref": "bob",
            "races_together": 2,
        },
        {
            "season": 2020,
            "constructor_ref": "xteam",
            "driver_ref": "bob",
            "teammate_ref": "ann",
            "races_together": 2,
        },
    ]


def test_unclassified_races_are_not_head_to_head_finishes(session: Session) -> None:
    """Cat (Yteam, 2020) had no teammate; nothing to compare."""
    assert not _rows(
        session,
        "SELECT 1 FROM v_head_to_head_teammates WHERE season = 2020 AND driver_ref = 'cat'",
    )


# --- documentation for the LLM ---


@pytest.mark.parametrize("view", VIEWS)
def test_views_are_documented(session: Session, view: str) -> None:
    comment = session.scalar(
        text("SELECT obj_description(CAST(:v AS regclass))"), {"v": view}
    )

    assert comment


def test_caveat_columns_are_documented(session: Session) -> None:
    def column_comment(view: str, column: str) -> str | None:
        return session.scalar(
            text(
                "SELECT col_description(CAST(:v AS regclass), a.attnum) FROM pg_attribute a "
                "WHERE a.attrelid = CAST(:v AS regclass) AND a.attname = :c"
            ),
            {"v": view, "c": column},
        )

    assert "grid" in column_comment("v_driver_career", "poles")
    assert "2004" in column_comment("v_driver_career", "fastest_laps_since_2004")
    assert "Approximate" in column_comment("v_driver_career", "race_starts")
