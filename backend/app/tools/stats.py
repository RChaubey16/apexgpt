"""The `query_stats` tool: run LLM-written SQL over the stats views (F3.5).

    tool = StatsTool.from_settings(settings)
    result = tool.run("SELECT driver_name, wins FROM v_driver_career ORDER BY wins DESC")
    result.to_payload()   # what goes back to the LLM

Layers, outermost first:
1. sql_guard.validate_stats_sql: Postgres's parser + allowlists; the query that
   runs is regenerated from the validated tree with a row limit.
2. The read-only role `apexgpt_llm_reader` (READONLY_DATABASE_URL): SELECT on
   the four views only, read-only by default, 5 connections (migration 0005).
3. Each query runs in its own READ ONLY transaction with this tool's own
   statement and lock timeouts (SET LOCAL), whatever the role defaults are.

Errors come back to the LLM as messages it can act on: a rejected query says
why, a database error gives Postgres's one-line message ('column "x" does not
exist'). Connection details, hosts and passwords never appear in either.
"""

import datetime as dt
import logging
import re
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import psycopg
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from app.core.config import Settings
from app.tools.base import ToolOutcome
from app.tools.sql_guard import STATS_VIEWS, UnsafeQueryError, validate_stats_sql

logger = logging.getLogger(__name__)

MAX_ROWS = 50
MAX_CELL_CHARS = 300
STATEMENT_TIMEOUT_MS = 3000
LOCK_TIMEOUT_MS = 1000

# Postgres error classes that mean the query itself is wrong (the LLM can fix
# it): 42 = syntax error or access rule violation, 22 = data exception,
# 21 = cardinality violation, 0A = feature not supported.
_QUERY_ERROR_CLASSES = ("42", "22", "21", "0A")
_QUERY_CANCELED = "57014"


class StatsToolError(Exception):
    """Base class; `str()` is safe to show the LLM."""


class StatsQueryRejected(StatsToolError):
    """The SQL failed validation."""


class StatsQueryFailed(StatsToolError):
    """The database refused the query (bad column, bad cast, timeout)."""


class StatsUnavailable(StatsToolError):
    """The stats database can't be reached or isn't configured."""


@dataclass(frozen=True)
class StatsResult:
    sql: str  # what ran (validated, deparsed, limited)
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    truncated: bool  # more rows existed than MAX_ROWS
    elapsed_ms: int

    def to_payload(self) -> dict[str, Any]:
        """JSON-ready result for the LLM's tool message."""
        payload: dict[str, Any] = {
            "columns": list(self.columns),
            "rows": [list(row) for row in self.rows],
            "row_count": len(self.rows),
        }
        if self.truncated:
            payload["note"] = (
                f"only the first {len(self.rows)} rows are shown; "
                "add ORDER BY and LIMIT or aggregate to narrow the result"
            )
        return payload


def json_value(value: Any) -> Any:
    """Make a database value JSON-safe and short enough for an LLM prompt."""
    if value is None or isinstance(value, bool | int | str):
        result = value
    elif isinstance(value, float):
        result = round(value, 6)
    elif isinstance(value, Decimal):
        result = int(value) if value == value.to_integral_value() else float(value)
    elif isinstance(value, dt.date | dt.datetime | dt.time):
        result = value.isoformat()
    elif isinstance(value, dt.timedelta):
        result = str(value)
    elif isinstance(value, list | tuple):
        return [json_value(v) for v in value]
    else:
        result = str(value)
    if isinstance(result, str) and len(result) > MAX_CELL_CHARS:
        result = result[:MAX_CELL_CHARS] + "…"
    return result


def _postgres_message(exc: Exception) -> tuple[str | None, str]:
    """(SQLSTATE, primary message) of a psycopg error (raw or wrapped by
    SQLAlchemy), without the LINE/context lines or connection details."""
    orig = exc.orig if isinstance(exc, DBAPIError) else exc
    diag = getattr(orig, "diag", None)
    sqlstate = getattr(orig, "sqlstate", None) or getattr(diag, "sqlstate", None)
    primary = getattr(diag, "message_primary", None) or "the query failed"
    return sqlstate, primary


NAME = "query_stats"


class StatsTool:
    name = NAME

    def __init__(self, engine: Engine | None, *, max_rows: int = MAX_ROWS) -> None:
        """engine=None means READONLY_DATABASE_URL is not configured."""
        self._engine = engine
        self._max_rows = max_rows
        self._schema: str | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> "StatsTool":
        url = settings.readonly_database_url
        if url is None:
            return cls(None)
        engine = create_engine(
            url.get_secret_value(),
            pool_pre_ping=True,
            pool_recycle=300,
            # The role allows 5 connections; leave room for psql and the CLI.
            pool_size=2,
            max_overflow=1,
            pool_timeout=5,
            connect_args={
                "connect_timeout": settings.database_connect_timeout,
                "application_name": "apexgpt-stats",
                "prepare_threshold": None,
            },
        )
        return cls(engine)

    def _require_engine(self) -> Engine:
        if self._engine is None:
            raise StatsUnavailable(
                "Statistics are not configured (READONLY_DATABASE_URL is not set)"
            )
        return self._engine

    def run(self, sql: str) -> StatsResult:
        """Validate and run one stats query. Raises a StatsToolError subclass."""
        try:
            query = validate_stats_sql(sql, max_rows=self._max_rows)
        except UnsafeQueryError as exc:
            logger.info("Stats query rejected: %s", exc)
            raise StatsQueryRejected(str(exc)) from None
        engine = self._require_engine()
        started = time.perf_counter()
        try:
            with engine.connect() as conn, conn.begin():
                conn.exec_driver_sql("SET TRANSACTION READ ONLY")
                conn.exec_driver_sql(
                    f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}"
                )
                conn.exec_driver_sql(f"SET LOCAL lock_timeout = {LOCK_TIMEOUT_MS}")
                # The driver's own cursor, with no parameters at all: psycopg then
                # sends the deparsed SQL exactly as validated. (Through SQLAlchemy,
                # '%' in ILIKE '%monza%' is read as a placeholder and the query
                # fails; ':name' would become a bind parameter.)
                with conn.connection.driver_connection.cursor() as cursor:
                    cursor.execute(query.sql)
                    columns = tuple(col.name for col in cursor.description or ())
                    fetched = cursor.fetchall()
        except (DBAPIError, psycopg.Error) as exc:
            sqlstate, message = _postgres_message(exc)
            logger.info(
                "Stats query failed: sqlstate=%s views=%s", sqlstate, query.views
            )
            if sqlstate == _QUERY_CANCELED:
                raise StatsQueryFailed(
                    f"the query took longer than {STATEMENT_TIMEOUT_MS // 1000} s; "
                    "simplify it or aggregate in fewer steps"
                ) from None
            if sqlstate and sqlstate.startswith(_QUERY_ERROR_CLASSES):
                raise StatsQueryFailed(message) from None
            logger.warning("Stats database error: %s", type(exc).__name__)
            raise StatsUnavailable("Statistics are unavailable right now") from None
        except SQLAlchemyError as exc:
            logger.warning("Stats database error: %s", type(exc).__name__)
            raise StatsUnavailable("Statistics are unavailable right now") from None

        elapsed = round((time.perf_counter() - started) * 1000)
        truncated = len(fetched) > self._max_rows
        rows = tuple(
            tuple(json_value(v) for v in row) for row in fetched[: self._max_rows]
        )
        logger.info(
            "Stats query ran: views=%s rows=%d truncated=%s elapsed_ms=%d",
            query.views,
            len(rows),
            truncated,
            elapsed,
        )
        return StatsResult(query.sql, columns, rows, truncated, elapsed)

    def schema(self) -> str:
        """The views, their columns, types and COMMENT ON text, for the LLM's
        tool description. Read once, as the read-only role, then cached."""
        if self._schema is None:
            engine = self._require_engine()
            try:
                with engine.connect() as conn:
                    rows = conn.execute(_SCHEMA_SQL, {"views": list(STATS_VIEWS)}).all()
            except SQLAlchemyError as exc:
                logger.warning("Stats schema failed to load: %s", type(exc).__name__)
                raise StatsUnavailable("Statistics are unavailable right now") from None
            self._schema = format_schema(rows)
        return self._schema

    def definition(self) -> dict[str, Any]:
        """The tool definition, with the live schema. Raises StatsUnavailable
        when the stats database isn't configured or reachable (don't offer it)."""
        return tool_definition(self.schema())

    def call(self, arguments: Any, **context: Any) -> ToolOutcome:
        """Run the model's `{"sql": ...}`; every expected failure becomes an
        error payload for the model (base.Tool)."""
        sql = arguments.get("sql") if isinstance(arguments, dict) else None
        if not isinstance(sql, str):
            return ToolOutcome.error(NAME, "arguments must be an object with 'sql'")
        try:
            result = self.run(sql)
        except StatsToolError as exc:
            return ToolOutcome.error(NAME, str(exc))
        return ToolOutcome(NAME, result.to_payload(), ok=True)

    def dispose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()


_SCHEMA_SQL = text("""
SELECT c.relname AS view, obj_description(c.oid, 'pg_class') AS view_comment,
       a.attname AS column, format_type(a.atttypid, a.atttypmod) AS type,
       col_description(c.oid, a.attnum) AS column_comment
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
WHERE c.relname = ANY(:views)
ORDER BY array_position(CAST(:views AS text[]), c.relname::text), a.attnum
""")


_SHORT_TYPES = (
    (re.compile(r"^(smallint|integer|bigint)$"), "int"),
    (re.compile(r"^numeric(\(.*\))?$"), "num"),
    (re.compile(r"^(character varying|character)(\(.*\))?$|^text$"), "text"),
    (re.compile(r"^timestamp.*$"), "timestamp"),
)


def _short_type(sql_type: str) -> str:
    for pattern, short in _SHORT_TYPES:
        if pattern.match(sql_type):
            return short
    return sql_type


def _first_sentence(comment: str) -> str:
    sentence = comment.split(". ")[0].strip()
    return sentence if sentence.endswith(".") else sentence + "."


def _described(column: str) -> bool:
    """Internal ids and URLs are left out of the description (the model never
    needs them: entity hints give refs); they can still be queried."""
    return not (column.endswith("_id") or column == "wikipedia_url")


def format_schema(rows: Any) -> str:
    """Compact text for the tool description (it goes with every LLM request,
    and the free tier counts tokens per minute): one block per view with its
    comment, the columns on one line with short types, then the column notes
    (first sentence of each COMMENT ON)."""
    views: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not _described(row.column):
            continue
        view = views.setdefault(
            row.view, {"comment": row.view_comment, "columns": [], "notes": []}
        )
        view["columns"].append(f"{row.column} {_short_type(row.type)}")
        if row.column_comment:
            view["notes"].append(f"{row.column}: {_first_sentence(row.column_comment)}")
    blocks = []
    for name, view in views.items():
        lines = [name + (f": {view['comment']}" if view["comment"] else "")]
        lines.append("  columns: " + ", ".join(view["columns"]))
        if view["notes"]:
            lines.append("  notes: " + " ".join(view["notes"]))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def tool_definition(schema: str) -> dict[str, Any]:
    """The OpenAI-format tool the orchestrator (F3.7) offers the LLM."""
    return {
        "type": "function",
        "function": {
            "name": NAME,
            "description": (
                "Run one read-only PostgreSQL SELECT over Formula 1 statistics "
                "(1950-2025) and get the rows back. Use it for counts, records, "
                "rankings, standings and comparisons. Only these views exist:\n\n"
                f"{schema}\n\n"
                "Rules: one SELECT (WITH/UNION allowed); only these views; "
                f"at most {MAX_ROWS} rows come back, so ORDER BY and LIMIT; match "
                "names with ILIKE or use the *_ref columns; no parameters. "
                "For 'most', 'fewest' or 'best' questions never use LIMIT 1: "
                "records are often shared (Monza wins: Hamilton and Schumacher, "
                "5 each), so return the top 5 or use rank() to keep ties."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "A single PostgreSQL SELECT statement.",
                    }
                },
                "required": ["sql"],
            },
        },
    }


def run(argv: list[str] | None = None) -> int:
    """`python -m app.tools.stats "SELECT ..."` or `--schema`: try the tool."""
    import argparse
    import json
    import sys

    from app.core.config import get_settings
    from app.core.logging import configure_logging

    parser = argparse.ArgumentParser(
        prog="python -m app.tools.stats",
        description="Run a stats query as the read-only role, as the LLM would.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("sql", nargs="?", help="one SELECT over the stats views")
    group.add_argument(
        "--schema", action="store_true", help="print the views the LLM sees"
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)
    tool = StatsTool.from_settings(settings)
    try:
        if args.schema:
            print(tool.schema())
            return 0
        result = tool.run(args.sql)
    except StatsQueryRejected as exc:
        print(f"rejected: {exc}", file=sys.stderr)
        return 2
    except StatsToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        tool.dispose()
    print(f"-- ran in {result.elapsed_ms} ms:\n{result.sql}\n")
    print(json.dumps(result.to_payload(), indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
