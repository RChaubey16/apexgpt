"""Database size guard: keep the data well inside Neon's free-tier storage (1 GB).

docs/DATA-STRATEGY.md §4: print each table's size after every load, warn at
700 MB of total database size, refuse to load at 900 MB.

The loaders check before they start and again before each commit (the
structured load is one transaction, so a load that would cross the limit rolls
back; the narrative sync commits in batches, so it stops at the next batch).
Sizes are pg_database_size(), which counts uncommitted rows already written.

    cd ingestion
    uv run python -m common.size_guard     # report only; exit 1 at or over the limit
"""

import argparse
import logging
import sys
from dataclasses import dataclass

import psycopg
from psycopg import sql
from pydantic import ValidationError

from structured.config import Settings
from structured.errors import IngestionError
from structured.load import connect

logger = logging.getLogger("common.size_guard")

MB = 1_000_000
WARN_BYTES = 700 * MB
REFUSE_BYTES = 900 * MB

_TABLE_SIZES = """
SELECT c.relname,
       pg_table_size(c.oid),
       pg_indexes_size(c.oid),
       pg_total_relation_size(c.oid)
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'm')
ORDER BY pg_total_relation_size(c.oid) DESC, c.relname
"""


class SizeLimitError(IngestionError):
    """The database is at or over the size limit: nothing more is loaded."""


@dataclass(frozen=True)
class TableSize:
    name: str
    rows: int
    table_bytes: int  # heap + TOAST
    index_bytes: int
    total_bytes: int


def database_size(conn: psycopg.Connection) -> int:
    row = conn.execute("SELECT pg_database_size(current_database())").fetchone()
    return int(row[0]) if row else 0


def table_sizes(conn: psycopg.Connection) -> list[TableSize]:
    """Sizes and exact row counts (the tables are small; estimates were misleading)."""
    sizes = conn.execute(_TABLE_SIZES).fetchall()
    tables = []
    for name, data, indexes, total in sizes:
        count = sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(name))
        row = conn.execute(count).fetchone()
        tables.append(TableSize(name, int(row[0]) if row else 0, data, indexes, total))
    return tables


def _mb(size: int) -> str:
    return f"{size / MB:,.1f} MB"


@dataclass(frozen=True)
class SizeGuard:
    warn_bytes: int = WARN_BYTES
    refuse_bytes: int = REFUSE_BYTES

    def __post_init__(self) -> None:
        if not 0 < self.warn_bytes <= self.refuse_bytes:
            raise ValueError("need 0 < warn_bytes <= refuse_bytes")

    def check(self, conn: psycopg.Connection, stage: str) -> int:
        """Raise SizeLimitError at or over the limit; warn past the warning level.

        `stage` says what is about to happen, for the messages ("before loading").
        """
        size = database_size(conn)
        if size >= self.refuse_bytes:
            raise SizeLimitError(
                f"database is {_mb(size)}, at or over the {_mb(self.refuse_bytes)} "
                f"limit ({stage}): refusing to load. Remove data or upgrade the "
                "Neon plan (docs/DATA-STRATEGY.md §6)"
            )
        if size >= self.warn_bytes:
            logger.warning(
                "Database is %s, past the %s warning level (limit %s)",
                _mb(size),
                _mb(self.warn_bytes),
                _mb(self.refuse_bytes),
            )
        return size

    def report(self, conn: psycopg.Connection) -> int:
        """Log every table's size and the database total; returns the total."""
        tables = table_sizes(conn)
        size = database_size(conn)
        logger.info(
            "%-24s %10s %12s %12s %12s", "table", "rows", "data", "indexes", "total"
        )
        for t in tables:
            logger.info(
                "%-24s %10s %12s %12s %12s",
                t.name,
                f"{t.rows:,}",
                _mb(t.table_bytes),
                _mb(t.index_bytes),
                _mb(t.total_bytes),
            )
        level = (
            "OVER THE LIMIT"
            if size >= self.refuse_bytes
            else "past the warning level" if size >= self.warn_bytes else "ok"
        )
        logger.log(
            logging.WARNING if size >= self.warn_bytes else logging.INFO,
            "Database size %s (tables %s): %s (warn %s, limit %s)",
            _mb(size),
            _mb(sum(t.total_bytes for t in tables)),
            level,
            _mb(self.warn_bytes),
            _mb(self.refuse_bytes),
        )
        return size


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m common.size_guard",
        description="Report table sizes against the database size budget.",
    )
    parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        settings = Settings()
    except ValidationError as exc:
        for error in exc.errors():
            logger.error(
                "Invalid setting %s: %s", ".".join(map(str, error["loc"])), error["msg"]
            )
        return 2
    if settings.database_url is None:
        logger.error("DATABASE_URL is not set (see .env.example)")
        return 2
    guard = SizeGuard(WARN_BYTES, REFUSE_BYTES)
    try:
        with connect(
            settings.database_url.get_secret_value(), settings.database_connect_timeout
        ) as conn:
            size = guard.report(conn)
    except psycopg.Error as exc:
        # Never log the exception text: it can echo connection details.
        logger.error("Database error: %s", type(exc).__name__)
        return 1
    return 1 if size >= guard.refuse_bytes else 0


if __name__ == "__main__":
    sys.exit(run())
