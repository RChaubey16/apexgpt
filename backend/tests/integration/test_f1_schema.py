"""Integration tests for the structured F1 schema (migration 0002) on real Postgres.

Skipped unless TEST_DATABASE_URL is set (see test_database.py for the warning:
these tests migrate up and down, so never point them at real data).
"""

import datetime as dt
import os
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, create_engine, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import normalise_database_url
from app.db.base import Base
from app.db.models import (
    Circuit,
    Constructor,
    ConstructorAlias,
    ConstructorLineage,
    ConstructorStanding,
    Driver,
    DriverAlias,
    DriverStanding,
    PitStop,
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

F1_TABLES = {
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
    "driver_aliases",
    "constructor_aliases",
    "constructor_lineage",
}


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


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """A session whose work is always rolled back, so tests don't share rows."""
    with engine.connect() as conn:
        trans = conn.begin()
        with Session(bind=conn, join_transaction_mode="create_savepoint") as s:
            yield s
        trans.rollback()


@pytest.fixture
def base_rows(session: Session) -> dict[str, int]:
    """One of each parent entity: a season, circuit, driver, team, status, race."""
    session.add_all(
        [
            Season(
                year=1988,
                wikipedia_url="https://en.wikipedia.org/wiki/1988_Formula_One_season",
            ),
            Circuit(
                circuit_id=1,
                ref="suzuka",
                name="Suzuka Circuit",
                locality="Suzuka",
                country="Japan",
                lat=34.8431,
                lng=136.541,
                altitude=45,
            ),
            Driver(
                driver_id=1,
                ref="senna",
                code="SEN",
                forename="Ayrton",
                surname="Senna",
                date_of_birth=dt.date(1960, 3, 21),
                nationality="Brazilian",
            ),
            Driver(driver_id=2, ref="prost", forename="Alain", surname="Prost"),
            Constructor(
                constructor_id=1, ref="mclaren", name="McLaren", nationality="British"
            ),
            Status(status="Finished"),
        ]
    )
    session.flush()
    session.add(
        Race(
            race_id=1,
            season=1988,
            round=15,
            name="Japanese Grand Prix",
            circuit_id=1,
            date=dt.date(1988, 10, 30),
        )
    )
    session.flush()
    status_id = session.scalar(
        select(Status.status_id).where(Status.status == "Finished")
    )
    assert status_id is not None
    return {"race_id": 1, "driver_id": 1, "constructor_id": 1, "status_id": status_id}


def _result(base: dict[str, int], result_id: int = 1, **overrides: object) -> Result:
    values: dict[str, object] = {
        "result_id": result_id,
        "race_id": base["race_id"],
        "driver_id": base["driver_id"],
        "constructor_id": base["constructor_id"],
        "status_id": base["status_id"],
        "grid": 1,
        "position": 1,
        "position_order": 1,
        "points": Decimal("9"),
        "laps": 51,
        "time_ms": 5_917_365,
    }
    values.update(overrides)
    return Result(**values)


# --- migration ---


def test_migration_matches_models(engine: Engine) -> None:
    """Migration 0002 and app/db/models must describe the same schema."""
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        diff = compare_metadata(ctx, Base.metadata)

    assert diff == []


def test_upgrade_creates_all_tables_and_no_lap_times(engine: Engine) -> None:
    tables = set(inspect(engine).get_table_names())

    assert tables >= F1_TABLES
    assert "lap_times" not in tables


def test_downgrade_to_0001_drops_f1_tables_but_keeps_pgvector(engine: Engine) -> None:
    command.downgrade(_alembic_config(), "0001")
    try:
        tables = set(inspect(engine).get_table_names())
        assert not (F1_TABLES & tables)
        with engine.connect() as conn:
            assert conn.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            ).scalar_one_or_none()
    finally:
        command.upgrade(_alembic_config(), "head")


# --- round trip ---


def test_full_race_weekend_round_trip(
    session: Session, base_rows: dict[str, int]
) -> None:
    b = base_rows
    session.add_all(
        [
            _result(
                b, fastest_lap_rank=1, fastest_lap_number=40, fastest_lap_ms=103_000
            ),
            SprintResult(
                sprint_result_id=1,
                race_id=b["race_id"],
                driver_id=b["driver_id"],
                constructor_id=b["constructor_id"],
                status_id=b["status_id"],
                grid=2,
                position=1,
                position_order=1,
                points=Decimal("8"),
                laps=17,
            ),
            Qualifying(
                race_id=b["race_id"],
                driver_id=b["driver_id"],
                constructor_id=b["constructor_id"],
                position=1,
                q1_ms=101_000,
            ),
            DriverStanding(
                race_id=b["race_id"],
                driver_id=1,
                points=Decimal("90"),
                position=1,
                wins=8,
            ),
            ConstructorStanding(
                race_id=b["race_id"],
                constructor_id=1,
                points=Decimal("199"),
                position=1,
                wins=15,
            ),
            PitStop(
                race_id=b["race_id"],
                driver_id=1,
                stop=1,
                lap=20,
                local_time=dt.time(14, 5, 30),
                duration_ms=23_500,
            ),
        ]
    )
    session.flush()
    session.expire_all()

    result = session.get(Result, 1)
    assert result is not None
    assert result.points == Decimal("9.00")
    assert result.time_ms == 5_917_365
    quali = session.scalar(select(Qualifying))
    assert quali is not None and quali.qualify_id is not None
    assert quali.q2_ms is None


def test_half_points_are_stored_exactly(
    session: Session, base_rows: dict[str, int]
) -> None:
    session.add(_result(base_rows, points=Decimal("1.5")))
    session.flush()
    session.expire_all()

    result = session.get(Result, 1)
    assert result is not None
    assert result.points == Decimal("1.50")


def test_shared_drives_are_allowed(session: Session, base_rows: dict[str, int]) -> None:
    """1950s: one driver in two cars, and two drivers sharing one car's position."""
    session.add_all(
        [
            _result(base_rows, result_id=1, position=5, position_order=5),
            _result(
                base_rows, result_id=2, position=None, position_order=12, number=99
            ),
            _result(base_rows, result_id=3, driver_id=2, position=5, position_order=5),
        ]
    )
    session.flush()


def test_unclassified_result_has_null_position(
    session: Session, base_rows: dict[str, int]
) -> None:
    session.add(_result(base_rows, position=None, position_order=20, time_ms=None))
    session.flush()


def test_an_alias_can_map_to_several_drivers(
    session: Session, base_rows: dict[str, int]
) -> None:
    session.add_all(
        [
            DriverAlias(alias="ayrton senna", driver_id=1, kind="name"),
            DriverAlias(alias="the professor", driver_id=2, kind="nickname"),
            DriverAlias(alias="champion", driver_id=1, kind="nickname"),
            DriverAlias(alias="champion", driver_id=2, kind="nickname"),
        ]
    )
    session.flush()

    ids = session.scalars(
        select(DriverAlias.driver_id).where(DriverAlias.alias == "champion")
    ).all()
    assert sorted(ids) == [1, 2]


def test_lineage_allows_a_team_to_return(
    session: Session, base_rows: dict[str, int]
) -> None:
    """Sauber -> BMW Sauber (2006) -> Sauber (2010): same pair, different seasons."""
    session.add(Constructor(constructor_id=2, ref="bmw_sauber", name="BMW Sauber"))
    session.flush()
    session.add_all(
        [
            ConstructorLineage(predecessor_id=1, successor_id=2, season=2006),
            ConstructorLineage(
                predecessor_id=2, successor_id=1, season=2010, note="BMW sold the team"
            ),
        ]
    )
    session.flush()


def test_deleting_a_driver_removes_their_aliases(
    session: Session, base_rows: dict[str, int]
) -> None:
    session.add(DriverAlias(alias="the professor", driver_id=2, kind="nickname"))
    session.flush()

    session.execute(text("DELETE FROM drivers WHERE driver_id = 2"))

    assert session.scalar(select(func.count()).select_from(DriverAlias)) == 0


def test_status_ids_are_generated(session: Session, base_rows: dict[str, int]) -> None:
    session.add_all([Status(status="Engine"), Status(status="+1 Lap")])
    session.flush()

    ids = session.scalars(select(Status.status_id)).all()
    assert len(set(ids)) == 3


def test_deleting_a_race_cascades_to_its_rows(
    session: Session, base_rows: dict[str, int]
) -> None:
    b = base_rows
    session.add_all(
        [
            _result(b),
            DriverStanding(
                race_id=b["race_id"],
                driver_id=1,
                points=Decimal("9"),
                position=1,
                wins=1,
            ),
            PitStop(
                race_id=b["race_id"], driver_id=1, stop=1, lap=20, duration_ms=23_500
            ),
        ]
    )
    session.flush()

    session.execute(text("DELETE FROM races WHERE race_id = :id"), {"id": b["race_id"]})

    for model in (Result, DriverStanding, PitStop):
        assert session.scalar(select(func.count()).select_from(model)) == 0


# --- constraints reject bad data ---

BAD_RESULTS = {
    "negative grid": {"grid": -1},
    "zero position": {"position": 0},
    "zero position order": {"position_order": 0},
    "negative points": {"points": Decimal("-1")},
    "negative laps": {"laps": -1},
    "zero time": {"time_ms": 0},
    "zero fastest lap": {"fastest_lap_ms": 0},
    "zero fastest lap number": {"fastest_lap_number": 0},
    "zero fastest lap rank": {"fastest_lap_rank": 0},
    "unknown driver": {"driver_id": 999},
    "unknown constructor": {"constructor_id": 999},
    "unknown race": {"race_id": 999},
    "unknown status": {"status_id": 999},
}


@pytest.mark.parametrize("overrides", BAD_RESULTS.values(), ids=BAD_RESULTS.keys())
def test_bad_results_are_rejected(
    session: Session, base_rows: dict[str, int], overrides: dict[str, object]
) -> None:
    session.add(_result(base_rows, **overrides))

    with pytest.raises(IntegrityError):
        session.flush()


BAD_ENTITIES = {
    "season before 1950": lambda: Season(year=1949),
    "latitude out of range": lambda: Circuit(
        circuit_id=2, ref="x", name="X", lat=91, lng=0
    ),
    "longitude out of range": lambda: Circuit(
        circuit_id=2, ref="x", name="X", lat=0, lng=181
    ),
    "driver code not 3 letters": lambda: Driver(
        driver_id=3, ref="x", code="AB", forename="A", surname="B"
    ),
    "duplicate driver ref": lambda: Driver(
        driver_id=3, ref="senna", forename="A", surname="B"
    ),
    "duplicate constructor ref": lambda: Constructor(
        constructor_id=2, ref="mclaren", name="X"
    ),
    "duplicate status text": lambda: Status(status="Finished"),
    "round zero": lambda: Race(
        race_id=2,
        season=1988,
        round=0,
        name="X",
        circuit_id=1,
        date=dt.date(1988, 1, 1),
    ),
    "duplicate season round": lambda: Race(
        race_id=2,
        season=1988,
        round=15,
        name="X",
        circuit_id=1,
        date=dt.date(1988, 1, 1),
    ),
    "race in unknown season": lambda: Race(
        race_id=2,
        season=1987,
        round=1,
        name="X",
        circuit_id=1,
        date=dt.date(1987, 1, 1),
    ),
    "duplicate qualifying entry": lambda: [
        Qualifying(race_id=1, driver_id=1, constructor_id=1, position=1),
        Qualifying(race_id=1, driver_id=1, constructor_id=1, position=2),
    ],
    "negative qualifying time": lambda: Qualifying(
        race_id=1, driver_id=1, constructor_id=1, q2_ms=-1
    ),
    "duplicate standing": lambda: [
        DriverStanding(race_id=1, driver_id=1, points=0, position=1, wins=0),
        DriverStanding(race_id=1, driver_id=1, points=0, position=2, wins=0),
    ],
    "negative wins": lambda: ConstructorStanding(
        race_id=1, constructor_id=1, points=0, position=1, wins=-1
    ),
    "zero pit duration": lambda: PitStop(
        race_id=1, driver_id=1, stop=1, lap=1, duration_ms=0
    ),
    "duplicate pit stop": lambda: [
        PitStop(race_id=1, driver_id=1, stop=1, lap=1, duration_ms=1),
        PitStop(race_id=1, driver_id=1, stop=1, lap=2, duration_ms=1),
    ],
    "alias with uppercase": lambda: DriverAlias(
        alias="Senna", driver_id=1, kind="surname"
    ),
    "alias with accents": lambda: DriverAlias(
        alias="pérez", driver_id=1, kind="surname"
    ),
    "alias with punctuation": lambda: DriverAlias(
        alias="o'ward", driver_id=1, kind="name"
    ),
    "alias with double space": lambda: DriverAlias(
        alias="a  b", driver_id=1, kind="name"
    ),
    "alias with outer space": lambda: DriverAlias(
        alias=" senna", driver_id=1, kind="name"
    ),
    "empty alias": lambda: DriverAlias(alias="", driver_id=1, kind="name"),
    "unknown driver alias kind": lambda: DriverAlias(
        alias="x", driver_id=1, kind="code"
    ),
    "constructor alias kind surname": lambda: ConstructorAlias(
        alias="x", constructor_id=1, kind="surname"
    ),
    "alias for unknown driver": lambda: DriverAlias(
        alias="x", driver_id=999, kind="name"
    ),
    "duplicate alias for same driver": lambda: [
        DriverAlias(alias="senna", driver_id=1, kind="surname"),
        DriverAlias(alias="senna", driver_id=1, kind="nickname"),
    ],
    "team succeeds itself": lambda: ConstructorLineage(
        predecessor_id=1, successor_id=1, season=2000
    ),
    "lineage before 1950": lambda: [
        Constructor(constructor_id=2, ref="x", name="X"),
        ConstructorLineage(predecessor_id=1, successor_id=2, season=1949),
    ],
}


@pytest.mark.parametrize("make", BAD_ENTITIES.values(), ids=BAD_ENTITIES.keys())
def test_bad_rows_are_rejected(
    session: Session, base_rows: dict[str, int], make: Callable[[], Base | list[Base]]
) -> None:
    rows = make()
    for row in rows if isinstance(rows, list) else [rows]:
        session.add(row)

    with pytest.raises(IntegrityError):
        session.flush()
