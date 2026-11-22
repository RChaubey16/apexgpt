"""StatsTool without a database: values, payloads, errors and the tool definition."""

import datetime as dt
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine

from app.tools import stats
from app.tools.stats import (
    MAX_CELL_CHARS,
    MAX_ROWS,
    StatsQueryRejected,
    StatsResult,
    StatsTool,
    StatsUnavailable,
    format_schema,
    json_value,
    tool_definition,
)
from tests.conftest import UNREACHABLE_DATABASE_URL, make_settings


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (True, True),
        (105, 105),
        ("Lewis Hamilton", "Lewis Hamilton"),
        (Decimal("127.33"), 127.33),
        (Decimal("98.00"), 98),
        (1 / 3, 0.333333),
        (dt.date(1976, 10, 24), "1976-10-24"),
        (dt.datetime(2021, 12, 12, 13, 0), "2021-12-12T13:00:00"),
        (dt.timedelta(minutes=1, seconds=31), "0:01:31"),
        ([Decimal("1.5"), dt.date(2000, 1, 1)], [1.5, "2000-01-01"]),
        (b"bytes", "b'bytes'"),
    ],
)
def test_values_are_made_json_safe(value: object, expected: object) -> None:
    assert json_value(value) == expected


def test_long_text_is_cut() -> None:
    cut = json_value("x" * 1000)

    assert len(cut) == MAX_CELL_CHARS + 1 and cut.endswith("…")


def test_payload_for_the_llm() -> None:
    result = StatsResult(
        sql="SELECT ...", columns=("driver_name", "wins"),
        rows=(("Lewis Hamilton", 105),), truncated=False, elapsed_ms=4,
    )  # fmt: skip

    assert result.to_payload() == {
        "columns": ["driver_name", "wins"],
        "rows": [["Lewis Hamilton", 105]],
        "row_count": 1,
    }


def test_payload_says_when_rows_were_cut_off() -> None:
    result = StatsResult("SELECT ...", ("x",), ((1,),) * MAX_ROWS, True, 4)

    payload = result.to_payload()
    assert payload["row_count"] == MAX_ROWS
    assert "only the first 50 rows" in payload["note"]


def test_without_a_readonly_url_the_tool_is_unavailable() -> None:
    tool = StatsTool.from_settings(make_settings(readonly_database_url=""))

    with pytest.raises(StatsUnavailable, match="READONLY_DATABASE_URL"):
        tool.run("SELECT * FROM v_driver_career")
    with pytest.raises(StatsUnavailable, match="not configured"):
        tool.schema()


def test_bad_sql_is_rejected_before_any_connection() -> None:
    tool = StatsTool(None)  # would raise StatsUnavailable if it got that far

    with pytest.raises(StatsQueryRejected, match="unknown table drivers"):
        tool.run("SELECT * FROM drivers")


def test_an_unreachable_database_is_a_safe_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine = create_engine(
        UNREACHABLE_DATABASE_URL.replace("postgresql://", "postgresql+psycopg://"),
        connect_args={"connect_timeout": 1},
    )
    tool = StatsTool(engine)

    with pytest.raises(StatsUnavailable, match="unavailable right now") as info:
        tool.run("SELECT * FROM v_driver_career")
    with pytest.raises(StatsUnavailable):
        tool.schema()

    assert info.value.__cause__ is None
    assert "127.0.0.1" not in str(info.value) and "test:test" not in caplog.text
    tool.dispose()


def test_from_settings_builds_a_small_pool_for_the_role() -> None:
    settings = make_settings(
        readonly_database_url="postgresql://apexgpt_llm_reader:pw-0123456789abcdef@localhost/apexgpt"
    )

    tool = StatsTool.from_settings(settings)

    engine = tool._engine
    assert engine is not None
    assert engine.url.username == "apexgpt_llm_reader"
    assert (
        engine.pool.size() + engine.pool._max_overflow <= 5
    )  # the role's connection limit
    tool.dispose()


def test_schema_text_lists_views_columns_and_comments() -> None:
    rows = [
        SimpleNamespace(view="v_driver_career", view_comment="One row per driver.",
                        column="driver_name", type="text", column_comment=None),
        SimpleNamespace(view="v_driver_career", view_comment="One row per driver.",
                        column="poles", type="bigint",
                        column_comment="Grid position 1. Qualifying only exists from 1994."),
        SimpleNamespace(view="v_driver_career", view_comment="One row per driver.",
                        column="driver_id", type="integer", column_comment=None),
        SimpleNamespace(view="v_driver_career", view_comment="One row per driver.",
                        column="wikipedia_url", type="text", column_comment=None),
        SimpleNamespace(view="v_season_summary", view_comment=None,
                        column="season", type="smallint", column_comment=None),
        SimpleNamespace(view="v_season_summary", view_comment=None,
                        column="code", type="character varying(3)", column_comment="Short code"),
        SimpleNamespace(view="v_season_summary", view_comment=None,
                        column="points", type="numeric(6,2)", column_comment=None),
    ]  # fmt: skip

    assert format_schema(rows) == (
        "v_driver_career: One row per driver.\n"
        "  columns: driver_name text, poles int\n"
        "  notes: poles: Grid position 1.\n"  # first sentence only
        "\n"
        "v_season_summary\n"
        "  columns: season int, code text, points num\n"
        "  notes: code: Short code."
    )  # ids and URLs are left out of the description


def test_tool_definition_for_the_llm() -> None:
    tool = tool_definition("v_driver_career\n  wins bigint")

    function = tool["function"]
    assert tool["type"] == "function" and function["name"] == "query_stats"
    assert "v_driver_career\n  wins bigint" in function["description"]
    assert f"at most {MAX_ROWS} rows" in function["description"]
    assert function["parameters"]["required"] == ["sql"]
    assert function["parameters"]["properties"]["sql"]["type"] == "string"


# --- CLI ---


def test_cli_rejected_query_exits_2(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr("app.core.config.get_settings", lambda: make_settings())

    assert stats.run(["SELECT * FROM drivers"]) == 2
    assert "rejected: unknown table drivers" in capsys.readouterr().err


def test_cli_unconfigured_exits_1(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(
        "app.core.config.get_settings", lambda: make_settings(readonly_database_url="")
    )

    assert stats.run(["--schema"]) == 1
    assert "not configured" in capsys.readouterr().err


def test_cli_needs_sql_or_schema() -> None:
    with pytest.raises(SystemExit) as info:
        stats.run([])
    assert info.value.code == 2
