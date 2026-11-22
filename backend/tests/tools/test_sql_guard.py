"""The stats tool's SQL validator: what the LLM may and may not run."""

import pytest

from app.tools.sql_guard import (
    MAX_SQL_CHARS,
    STATS_VIEWS,
    UnsafeQueryError,
    validate_stats_sql,
)


def ok(sql: str, max_rows: int = 50):
    return validate_stats_sql(sql, max_rows=max_rows)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT driver_name, wins FROM v_driver_career ORDER BY wins DESC LIMIT 5",
        "select * from v_driver_career;",
        "SELECT driver_name, count(*) AS wins FROM v_race_winners "
        "WHERE circuit_name ILIKE '%monza%' GROUP BY 1 ORDER BY 2 DESC",
        "WITH t AS (SELECT season, champion_name FROM v_season_summary) "
        "SELECT * FROM t WHERE season BETWEEN 1976 AND 1980",
        "WITH RECURSIVE t AS (SELECT season FROM v_season_summary) SELECT * FROM t",
        "SELECT round(CAST(wins AS numeric) / nullif(race_starts, 0) * 100, 1) "
        "FROM v_driver_career WHERE race_starts > 50",
        "SELECT season FROM v_season_summary UNION SELECT season FROM v_race_winners",
        "SELECT season FROM v_season_summary INTERSECT SELECT season FROM v_race_winners",
        "SELECT w.driver_name, s.season FROM v_race_winners w "
        "JOIN v_season_summary s ON s.season = w.season LEFT JOIN v_driver_career c USING (driver_id)",
        "SELECT * FROM (SELECT driver_name FROM v_driver_career) AS sub",
        "SELECT driver_name FROM v_driver_career WHERE driver_id IN "
        "(SELECT driver_id FROM v_race_winners WHERE season = 1988)",
        "SELECT driver_name, rank() OVER (ORDER BY wins DESC), "
        "lag(wins) OVER (PARTITION BY nationality ORDER BY wins) FROM v_driver_career",
        "SELECT CASE WHEN wins > 10 THEN 'great' ELSE 'ok' END, coalesce(poles, 0), "
        "greatest(wins, poles) FROM v_driver_career",
        "SELECT extract(year FROM race_date), date_trunc('month', race_date), "
        "to_char(race_date, 'YYYY'), CURRENT_DATE FROM v_race_winners",
        "SELECT string_agg(driver_name, ', ' ORDER BY driver_name), "
        "count(*) FILTER (WHERE wins > 0) FROM v_driver_career",
        "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY wins) FROM v_driver_career",
        "SELECT driver_name FROM v_driver_career WHERE driver_name IS NOT NULL "
        "AND wins IS DISTINCT FROM 0 AND nationality LIKE 'Brit%' AND wins IN (1, 2)",
        "SELECT driver_name FROM public.v_driver_career",
        "SELECT * FROM v_driver_career FETCH FIRST 3 ROWS ONLY",
        "SELECT season, count(*) FROM v_race_winners GROUP BY ROLLUP (season)",
        "SELECT * FROM v_head_to_head_teammates WHERE season = 2016",
    ],
)
def test_ordinary_stats_queries_are_allowed(sql: str) -> None:
    assert ok(sql).views


@pytest.mark.parametrize(
    ("sql", "message"),
    [
        # Not one SELECT
        ("SELECT 1 FROM v_driver_career; SELECT 2 FROM v_driver_career", "exactly one"),
        ("DELETE FROM v_driver_career", "single SELECT"),
        ("UPDATE drivers SET surname = 'x'", "single SELECT"),
        ("INSERT INTO drivers VALUES (1)", "single SELECT"),
        ("DROP VIEW v_driver_career", "single SELECT"),
        ("SET statement_timeout = 0", "single SELECT"),
        ("RESET ROLE", "single SELECT"),
        ("COPY (SELECT 1) TO '/tmp/x'", "single SELECT"),
        ("EXPLAIN ANALYZE SELECT * FROM v_driver_career", "single SELECT"),
        ("CALL something()", "single SELECT"),
        ("DO $$ BEGIN PERFORM 1; END $$", "single SELECT"),
        ("VALUES (1), (2)", "must read from"),
        # Hidden writes and locks
        (
            "WITH d AS (DELETE FROM drivers RETURNING *) SELECT * FROM d",
            "single SELECT",
        ),
        (
            "WITH u AS (UPDATE drivers SET ref = 'x' RETURNING *) SELECT * FROM v_driver_career",
            "single SELECT",
        ),
        ("SELECT * INTO new_table FROM v_driver_career", "INTO"),
        ("SELECT * FROM v_driver_career FOR UPDATE", "FOR UPDATE"),
        ("SELECT * FROM v_driver_career FOR SHARE NOWAIT", "FOR UPDATE"),
        # Other tables, schemas and databases
        ("SELECT * FROM drivers", "unknown table drivers"),
        ("SELECT * FROM public.results", "unknown table results"),
        ("SELECT * FROM pg_catalog.pg_authid", "only the stats views"),
        ("SELECT * FROM pg_roles", "unknown table pg_roles"),
        ("SELECT * FROM information_schema.tables", "only the stats views"),
        ("SELECT * FROM otherdb.public.v_driver_career", "only the stats views"),
        (
            "SELECT * FROM v_driver_career WHERE driver_id IN (SELECT driver_id FROM results)",
            "unknown table results",
        ),
        (
            "SELECT * FROM v_driver_career, LATERAL (SELECT * FROM drivers) d",
            "unknown table drivers",
        ),
        (
            "WITH x AS (SELECT * FROM drivers) SELECT * FROM v_driver_career",
            "unknown table drivers",
        ),
        ("SELECT 1", "must read from"),
        # Dangerous functions, casts and values
        (
            "SELECT set_config('statement_timeout', '0', false) FROM v_driver_career",
            "set_config",
        ),
        (
            "SELECT current_setting('search_path') FROM v_driver_career",
            "current_setting",
        ),
        ("SELECT pg_sleep(10) FROM v_driver_career", "pg_sleep"),
        ("SELECT pg_catalog.pg_sleep(10) FROM v_driver_career", "pg_sleep"),
        (
            "SELECT query_to_xml('select 1', true, true, '') FROM v_driver_career",
            "query_to_xml",
        ),
        ("SELECT pg_read_file('/etc/passwd') FROM v_driver_career", "pg_read_file"),
        ("SELECT lo_import('/etc/passwd') FROM v_driver_career", "lo_import"),
        ("SELECT dblink('host=x', 'select 1') FROM v_driver_career", "dblink"),
        ("SELECT public.lower(driver_name) FROM v_driver_career", "lower"),
        ("SELECT pg_terminate_backend(1) FROM v_driver_career", "pg_terminate_backend"),
        ("SELECT txid_current() FROM v_driver_career", "txid_current"),
        ("SELECT 'pg_authid'::regclass FROM v_driver_career", "regclass"),
        ("SELECT CAST('now' AS regproc) FROM v_driver_career", "regproc"),
        ("SELECT current_user FROM v_driver_career", "CURRENT_DATE"),
        ("SELECT session_user FROM v_driver_career", "CURRENT_DATE"),
        ("SELECT * FROM generate_series(1, 10)", "functions in FROM"),
        (
            "SELECT * FROM v_driver_career, generate_series(1, 1000000)",
            "functions in FROM",
        ),
        ("SELECT * FROM v_driver_career TABLESAMPLE SYSTEM (10)", "RangeTableSample"),
        ("SELECT $1 FROM v_driver_career", "parameters"),
        (
            "SELECT * FROM v_driver_career LIMIT (SELECT 5)",
            "LIMIT must be a plain number",
        ),
        ("SELECT * FROM v_driver_career LIMIT wins", "LIMIT must be a plain number"),
        # Malformed or oversized
        ("", "empty"),
        ("   ", "empty"),
        ("SELEC * FROM v_driver_career", "syntax error"),
        ("SELECT * FROM v_driver_career WHERE name = :name", "syntax error"),
        (
            "SELECT 1 FROM v_driver_career WHERE "  # noqa: S608 (test input)
            + " OR ".join(["wins = 1"] * 400),
            "longer than",
        ),
    ],
)
def test_unsafe_or_invalid_queries_are_rejected(sql: str, message: str) -> None:
    with pytest.raises(UnsafeQueryError, match=message):
        ok(sql)


def test_non_strings_are_rejected() -> None:
    with pytest.raises(UnsafeQueryError, match="empty"):
        validate_stats_sql(None, max_rows=5)  # type: ignore[arg-type]


def test_the_max_length_is_reasonable() -> None:
    assert 2000 <= MAX_SQL_CHARS <= 10_000


# --- what runs ---


def test_a_missing_limit_is_added() -> None:
    query = ok("SELECT driver_name FROM v_driver_career", max_rows=50)

    assert query.sql.endswith("LIMIT 51")  # one extra row reveals truncation


def test_a_large_limit_is_lowered_and_a_small_one_kept() -> None:
    assert ok("SELECT * FROM v_driver_career LIMIT 1000", 50).sql.endswith("LIMIT 51")
    assert ok("SELECT * FROM v_driver_career LIMIT 51", 50).sql.endswith("LIMIT 51")
    assert ok("SELECT * FROM v_driver_career LIMIT 3", 50).sql.endswith("LIMIT 3")


def test_fetch_first_is_limited_too() -> None:
    assert ok(
        "SELECT * FROM v_driver_career FETCH FIRST 500 ROWS ONLY", 10
    ).sql.endswith("LIMIT 11")


def test_the_limit_applies_to_the_whole_union() -> None:
    sql = ok(
        "SELECT season FROM v_season_summary UNION SELECT season FROM v_race_winners", 5
    ).sql

    assert sql.endswith("LIMIT 6")
    assert sql.count("LIMIT") == 1


def test_inner_limits_are_left_alone() -> None:
    sql = ok("SELECT * FROM (SELECT * FROM v_driver_career LIMIT 500) s", 5).sql

    assert "LIMIT 500" in sql and sql.endswith("LIMIT 6")


def test_the_query_that_runs_is_regenerated_from_the_tree() -> None:
    query = ok(
        "select driver_name,wins from v_driver_career -- a comment\nwhere wins>0;"
    )

    assert query.sql == (
        "SELECT driver_name, wins FROM v_driver_career WHERE wins > 0 LIMIT 51"
    )
    assert query.views == ("v_driver_career",)


def test_string_literals_survive_regeneration() -> None:
    sql = ok("SELECT 'it''s', '%monza%', ':name', 'a;b' FROM v_driver_career").sql

    assert (
        "'it''s'" in sql and "'%monza%'" in sql and "':name'" in sql and "'a;b'" in sql
    )


def test_views_read_are_reported() -> None:
    query = ok(
        "SELECT * FROM v_race_winners w JOIN v_driver_career d USING (driver_id) "
        "WHERE w.season IN (SELECT season FROM v_season_summary)"
    )

    assert query.views == ("v_driver_career", "v_race_winners", "v_season_summary")


def test_cte_names_are_not_views_and_a_cte_alone_is_not_enough() -> None:
    with pytest.raises(UnsafeQueryError, match="must read from"):
        ok("WITH t AS (SELECT 1 AS x) SELECT * FROM t")


def test_a_cte_cannot_be_schema_qualified() -> None:
    with pytest.raises(UnsafeQueryError, match="unknown table t"):
        ok("WITH t AS (SELECT * FROM v_driver_career) SELECT * FROM public.t")


def test_the_view_list_is_the_four_stats_views() -> None:
    assert STATS_VIEWS == (
        "v_race_winners",
        "v_driver_career",
        "v_season_summary",
        "v_head_to_head_teammates",
    )
