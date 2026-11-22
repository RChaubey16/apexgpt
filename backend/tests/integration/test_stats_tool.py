"""StatsTool on real Postgres, acting as the read-only role (F3.5).

The tool's connections run `SET ROLE apexgpt_llm_reader`, so queries have
exactly the role's privileges without touching its password (roles are
cluster-wide; see test_readonly_role.py). Skipped unless TEST_DATABASE_URL is set.
"""

import datetime as dt
from collections.abc import Iterator
from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session

from app.db.models import Circuit, Constructor, Driver, Race, Result, Season, Status
from app.tools.sql_guard import STATS_VIEWS
from app.tools.stats import StatsQueryFailed, StatsTool
from tests.integration import test_f1_schema as f1

pytestmark = pytest.mark.integration
ROLE = "apexgpt_llm_reader"


@pytest.fixture(scope="module")
def admin() -> Iterator[Engine]:
    """A migrated schema with one season of committed data, reset afterwards."""
    command.downgrade(f1._alembic_config(), "base")
    command.upgrade(f1._alembic_config(), "head")
    engine = create_engine(f1.DATABASE_URL, connect_args={"prepare_threshold": None})
    with Session(engine) as s:
        s.add_all(
            [
                Season(year=1988, wikipedia_url="https://en.wikipedia.org/wiki/1988"),
                Circuit(circuit_id=1, ref="monza", name="Autodromo Nazionale di Monza",
                        locality="Monza", country="Italy"),
                Driver(driver_id=1, ref="senna", forename="Ayrton", surname="Senna"),
                Driver(driver_id=2, ref="berger", forename="Gerhard", surname="Berger"),
                Constructor(constructor_id=1, ref="mclaren", name="McLaren"),
                Constructor(constructor_id=2, ref="ferrari", name="Ferrari"),
                Status(status="Finished"),
            ]
        )  # fmt: skip
        s.flush()
        s.add_all(
            [
                Race(race_id=1, season=1988, round=1, name="Italian Grand Prix",
                     circuit_id=1, date=dt.date(1988, 9, 11)),
                Race(race_id=2, season=1988, round=2, name="Italian Grand Prix II",
                     circuit_id=1, date=dt.date(1988, 9, 25)),
            ]
        )  # fmt: skip
        s.flush()
        status = s.query(Status).one().status_id
        for result_id, (race, driver, team, pos) in enumerate(
            [(1, 2, 2, 1), (1, 1, 1, 2), (2, 1, 1, 1), (2, 2, 2, 2)], start=1
        ):
            s.add(
                Result(result_id=result_id, race_id=race, driver_id=driver,
                       constructor_id=team, status_id=status, grid=pos, position=pos,
                       position_order=pos, points=Decimal(9 if pos == 1 else 6), laps=51)
            )  # fmt: skip
        s.commit()
    yield engine
    engine.dispose()
    command.downgrade(f1._alembic_config(), "base")


@pytest.fixture
def reader_engine(admin: Engine) -> Iterator[Engine]:
    engine = create_engine(f1.DATABASE_URL, connect_args={"prepare_threshold": None})

    @event.listens_for(engine, "connect")
    def act_as_reader(dbapi_connection, record):  # noqa: ANN001
        with dbapi_connection.cursor() as cur:
            cur.execute(f"SET ROLE {ROLE}")
        dbapi_connection.commit()

    yield engine
    engine.dispose()


@pytest.fixture
def tool(reader_engine: Engine) -> StatsTool:
    return StatsTool(reader_engine)


def test_a_query_runs_as_the_reader(tool: StatsTool) -> None:
    result = tool.run(
        "SELECT driver_name, count(*) AS wins FROM v_race_winners "
        "WHERE circuit_name ILIKE '%monza%' GROUP BY 1 ORDER BY 2 DESC, 1"
    )

    assert result.columns == ("driver_name", "wins")
    assert result.rows == (("Ayrton Senna", 1), ("Gerhard Berger", 1))
    assert not result.truncated and result.elapsed_ms >= 0
    assert result.sql.endswith("LIMIT 51")


def test_values_come_back_json_safe(tool: StatsTool) -> None:
    result = tool.run(
        "SELECT race_date, points, driver_name FROM v_race_winners ORDER BY race_date"
    )

    assert result.rows[0] == ("1988-09-11", 9, "Gerhard Berger")


def test_literals_with_percent_colon_and_quotes_run_unchanged(tool: StatsTool) -> None:
    result = tool.run(
        "SELECT driver_name FROM v_driver_career "
        "WHERE driver_name LIKE '%a%' AND driver_name <> ':x' AND driver_name <> 'it''s' "
        "ORDER BY 1"
    )

    assert result.rows == (("Ayrton Senna",), ("Gerhard Berger",))


def test_more_rows_than_the_cap_are_flagged(reader_engine: Engine) -> None:
    result = StatsTool(reader_engine, max_rows=1).run(
        "SELECT driver_name FROM v_driver_career ORDER BY 1"
    )

    assert result.rows == (("Ayrton Senna",),)
    assert result.truncated
    assert "only the first 1 rows" in result.to_payload()["note"]


@pytest.mark.parametrize(
    ("sql", "message"),
    [
        (
            "SELECT no_such_column FROM v_driver_career",
            'column "no_such_column" does not exist',
        ),
        (
            "SELECT CAST(driver_name AS integer) FROM v_driver_career",
            "invalid input syntax",
        ),
        ("SELECT 1 / (wins - wins) FROM v_driver_career", "division by zero"),
        (
            "SELECT season FROM v_season_summary WHERE season = "
            "(SELECT season FROM v_race_winners)",
            "more than one row",
        ),
    ],
)
def test_database_errors_are_one_line_messages_for_the_llm(
    tool: StatsTool, sql: str, message: str
) -> None:
    with pytest.raises(StatsQueryFailed, match=message) as info:
        tool.run(sql)

    assert "\n" not in str(info.value) and "LINE" not in str(info.value)


def test_the_connection_is_usable_after_an_error(tool: StatsTool) -> None:
    with pytest.raises(StatsQueryFailed):
        tool.run("SELECT nope FROM v_driver_career")

    assert tool.run("SELECT count(*) FROM v_driver_career").rows == ((2,),)


def test_the_schema_lists_the_views_with_their_comments(tool: StatsTool) -> None:
    schema = tool.schema()

    for view in STATS_VIEWS:
        assert f"\n{view}" in f"\n{schema}"
    assert "driver_name text" in schema and "poles int" in schema
    assert "notes: " in schema and "poles: " in schema  # COMMENT ON text (0004)
    assert "driver_id" not in schema  # ids are left out of the description
    assert tool.schema() is schema  # cached


def test_the_validator_allows_exactly_the_views_the_role_can_read(
    admin: Engine,
) -> None:
    with admin.connect() as conn:
        granted = set(
            conn.execute(
                text(
                    "SELECT table_name FROM information_schema.role_table_grants "
                    "WHERE grantee = :role AND privilege_type = 'SELECT'"
                ),
                {"role": ROLE},
            ).scalars()
        )

    assert granted == set(STATS_VIEWS)


def test_the_transaction_is_read_only_and_uses_the_tools_timeouts(
    reader_engine: Engine, admin: Engine
) -> None:
    """What the tool sets, checked from the same kind of connection."""
    with reader_engine.connect() as conn, conn.begin():
        conn.exec_driver_sql("SET TRANSACTION READ ONLY")
        conn.exec_driver_sql("SET LOCAL statement_timeout = 3000")
        values = conn.execute(
            text(
                "SELECT current_setting('transaction_read_only'), "
                "current_setting('statement_timeout'), current_user"
            )
        ).one()

    assert values == ("on", "3s", ROLE)
