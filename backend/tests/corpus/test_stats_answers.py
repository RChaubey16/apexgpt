"""The stats tool on the real data, as the read-only role (F3.5).

Opt-in and read-only, like the other corpus tests:

    CORPUS_DATABASE_URL=postgresql://…/apexgpt uv run pytest -m corpus

Known answers through hand-written SQL (the LLM's part is tests/live), and the
tool's own statement timeout stopping a runaway query.
"""

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, event

from app.core.config import normalise_database_url
from app.tools.stats import STATEMENT_TIMEOUT_MS, StatsQueryFailed, StatsTool

pytestmark = pytest.mark.corpus

_URL = os.environ.get("CORPUS_DATABASE_URL")
if not _URL:
    pytest.skip("CORPUS_DATABASE_URL not set", allow_module_level=True)


@pytest.fixture(scope="module")
def tool() -> Iterator[StatsTool]:
    engine: Engine = create_engine(
        normalise_database_url(_URL), connect_args={"prepare_threshold": None}
    )

    @event.listens_for(engine, "connect")
    def act_as_reader(dbapi_connection, record):  # noqa: ANN001
        with dbapi_connection.cursor() as cur:
            cur.execute("SET ROLE apexgpt_llm_reader")
        dbapi_connection.commit()

    yield StatsTool(engine)
    engine.dispose()


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        (
            "SELECT driver_name, wins FROM v_driver_career ORDER BY wins DESC LIMIT 2",
            (("Lewis Hamilton", 105), ("Michael Schumacher", 91)),
        ),
        (
            "SELECT driver_name, count(*) FROM v_race_winners WHERE circuit_name "
            "ILIKE '%monza%' GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 2",
            (("Lewis Hamilton", 5), ("Michael Schumacher", 5)),
        ),
        (
            "SELECT champion_name FROM v_season_summary WHERE season = 1976",
            (("James Hunt",),),
        ),
        (
            "SELECT wins, poles FROM v_driver_career WHERE driver_ref = 'senna'",
            ((41, 65),),
        ),
        (
            "SELECT constructors_champion_name FROM v_season_summary WHERE season = 2009",
            (("Brawn",),),
        ),
        ("SELECT count(*) FROM v_season_summary", ((76,),)),
    ],
)
def test_known_answers(tool: StatsTool, sql: str, expected: tuple) -> None:
    assert tool.run(sql).rows == expected


def test_the_tools_timeout_stops_a_runaway_query(tool: StatsTool) -> None:
    with pytest.raises(
        StatsQueryFailed, match=f"longer than {STATEMENT_TIMEOUT_MS // 1000} s"
    ):
        tool.run(
            "SELECT count(*) FROM v_head_to_head_teammates a, "
            "v_head_to_head_teammates b, v_head_to_head_teammates c"
        )


def test_the_full_schema_fits_in_a_tool_description(tool: StatsTool) -> None:
    schema = tool.schema()

    assert 1000 < len(schema) < 6000  # ~1,000 tokens: sent with every LLM request
    assert "fastest_laps_since_2004" in schema
