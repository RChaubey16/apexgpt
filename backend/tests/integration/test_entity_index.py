"""load_entity_index against real Postgres: the SQL behind entity resolution (F3.4).

Skipped unless TEST_DATABASE_URL is set (see test_database.py for the warning).
"""

import datetime as dt

import pytest
from sqlalchemy.orm import Session

from app.db.models import ConstructorAlias, Driver, DriverAlias, Race
from app.retrieval.entities import EntityResolver, load_entity_index
from tests.integration import test_f1_schema as f1

pytestmark = pytest.mark.integration

# The F1 schema tests' migrated engine, rolled-back session and parent rows:
# season 1988, Suzuka (circuit 1), Senna (driver 1), Prost (2), McLaren (1),
# the 1988 Japanese GP (race 1).
engine = f1.engine
session = f1.session
base_rows = f1.base_rows


@pytest.fixture
def seeded(session: Session, base_rows: dict[str, int]) -> Session:
    session.add_all(
        [
            Driver(driver_id=3, ref="nobody", forename="Never", surname="Raced"),
            Race(
                race_id=2,
                season=1988,
                round=16,
                name="Australian Grand Prix",
                circuit_id=1,  # a second race at Suzuka, for the count
                date=dt.date(1988, 11, 13),
            ),
        ]
    )
    session.flush()
    session.add_all(
        [
            f1._result(base_rows, 1),  # Senna wins race 1 for McLaren
            f1._result(base_rows, 2, driver_id=2, position=2, position_order=2, grid=2),
            f1._result(base_rows, 3, race_id=2, driver_id=2),  # Prost wins race 2
            DriverAlias(alias="ayrton senna", driver_id=1, kind="name"),
            DriverAlias(alias="senna", driver_id=1, kind="surname"),
            DriverAlias(alias="magic", driver_id=1, kind="nickname"),
            DriverAlias(alias="alain prost", driver_id=2, kind="name"),
            DriverAlias(alias="prost", driver_id=2, kind="surname"),
            DriverAlias(alias="the professor", driver_id=2, kind="nickname"),
            DriverAlias(alias="raced", driver_id=3, kind="surname"),
            ConstructorAlias(alias="mclaren", constructor_id=1, kind="name"),
            ConstructorAlias(alias="macca", constructor_id=1, kind="nickname"),
        ]
    )
    session.flush()
    return session


def test_index_reads_aliases_seasons_and_records(seeded: Session) -> None:
    index = load_entity_index(seeded)

    (senna,) = [e for e, _ in index.aliases["senna"]]
    assert (senna.kind, senna.id, senna.ref, senna.name) == (
        "driver",
        1,
        "senna",
        "Ayrton Senna",
    )
    assert senna.seasons == {1988} and (senna.wins, senna.races) == (1, 1)
    (prost,) = [e for e, _ in index.aliases["the professor"]]
    assert (prost.wins, prost.races) == (1, 2)

    mclaren, match = index.aliases["macca"][0]
    assert (mclaren.kind, match) == ("constructor", "nickname")
    assert (mclaren.wins, mclaren.races) == (2, 2)  # each race counted once
    assert mclaren.seasons == {1988}

    (never,) = [e for e, _ in index.aliases["raced"]]
    assert never.seasons == frozenset() and (never.wins, never.races) == (0, 0)


def test_circuits_get_aliases_from_ref_name_and_locality(seeded: Session) -> None:
    index = load_entity_index(seeded)

    for alias in ("suzuka", "suzuka circuit"):
        suzuka, match = index.aliases[alias][0]
        assert (suzuka.kind, suzuka.ref, match) == ("circuit", "suzuka", "circuit")
    assert suzuka.races == 2 and suzuka.seasons == {1988}


def test_curated_circuit_names_for_missing_circuits_are_skipped(
    seeded: Session, caplog: pytest.LogCaptureFixture
) -> None:
    index = load_entity_index(seeded)

    assert "singapore" not in index.aliases  # marina_bay isn't in this database
    assert "points at unknown circuit 'marina_bay'" in caplog.text


def test_resolving_against_the_loaded_index(seeded: Session) -> None:
    resolution = EntityResolver(lambda: load_entity_index(seeded)).resolve(
        "Did Magic beat the Professor at Suzuka for McLaren in 1988?"
    )

    assert [
        (m.text, m.best.entity.ref, m.best.active) for m in resolution.mentions
    ] == [
        ("Magic", "senna", True),
        ("the Professor", "prost", True),
        ("Suzuka", "suzuka", True),
        ("McLaren", "mclaren", True),
    ]
