"""Copy the loaded data from the local database into Neon (F7.2).

    cd ingestion
    TARGET_DATABASE_URL=postgresql://…neon.tech/apexgpt?sslmode=require \
      uv run python -m restore              # DATABASE_URL (from .env) is the source

The target must already have the schema (`alembic upgrade head`, at the same
revision as the source). Every data table is streamed with COPY (no pg_dump,
so no client/server version match is needed) into **one transaction** on the
target, in foreign-key order. Before it commits:

- row counts must match the source, table by table;
- the size guard must pass (900 MB refuses, docs/DATA-STRATEGY.md §4);
- the structured sanity checks must pass (structured/checks.py).

Any failure rolls the whole restore back. Not copied: `alembic_version` (the
migrations own it) and `feedback` (local test ratings).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from graphlib import CycleError, TopologicalSorter
from urllib.parse import parse_qs, urlsplit

import psycopg
from psycopg import sql

from common.size_guard import REFUSE_BYTES, WARN_BYTES, SizeGuard
from structured.checks import CHECKS, Check, run_checks
from structured.errors import IngestionError

logger = logging.getLogger("restore")

EXCLUDED_TABLES = frozenset({"alembic_version", "feedback"})
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "host.docker.internal", "db"})
SECURE_SSLMODES = frozenset({"require", "verify-ca", "verify-full"})


class RestoreError(IngestionError):
    """The restore can't run, or failed and was rolled back (safe to show)."""


# --- the two URLs -----------------------------------------------------------------


def _where(url: str) -> tuple[str, int, str]:
    parts = urlsplit(url)
    return (parts.hostname or "", parts.port or 5432, parts.path.strip("/"))


def check_urls(source: str, target: str) -> None:
    """Refuse to restore into the source itself, or over plain text to a
    remote host. Errors never include the URLs (they hold passwords)."""
    if _where(source) == _where(target):
        raise RestoreError("the target is the source database")
    host = _where(target)[0]
    sslmode = parse_qs(urlsplit(target).query).get("sslmode", [""])[-1]
    if host not in LOCAL_HOSTS and sslmode not in SECURE_SSLMODES:
        raise RestoreError(
            "a remote target needs TLS: add ?sslmode=require (Neon's connection "
            "strings include it)"
        )


# --- what to copy -------------------------------------------------------------------

_TABLES = """
SELECT c.relname
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r'
ORDER BY c.relname
"""

_COLUMNS = """
SELECT attname FROM pg_attribute
WHERE attrelid = to_regclass(%s) AND attnum > 0 AND NOT attisdropped
  AND attgenerated = ''
ORDER BY attnum
"""

_FOREIGN_KEYS = """
SELECT c.conrelid::regclass::text, c.confrelid::regclass::text
FROM pg_constraint c
JOIN pg_namespace n ON n.oid = c.connamespace
WHERE c.contype = 'f' AND n.nspname = 'public'
"""


def revision(cur: psycopg.Cursor) -> str | None:
    cur.execute("SELECT to_regclass('public.alembic_version') IS NOT NULL")
    if not cur.fetchone()[0]:
        return None
    cur.execute("SELECT version_num FROM alembic_version")
    row = cur.fetchone()
    return row[0] if row else None


def data_tables(cur: psycopg.Cursor) -> list[str]:
    cur.execute(_TABLES)
    return [name for (name,) in cur.fetchall() if name not in EXCLUDED_TABLES]


def columns(cur: psycopg.Cursor, table: str) -> list[str]:
    cur.execute(_COLUMNS, (f"public.{table}",))
    return [name for (name,) in cur.fetchall()]


def load_order(
    tables: Iterable[str], foreign_keys: Iterable[tuple[str, str]]
) -> list[str]:
    """Tables ordered so that every referenced table comes first; ties are
    alphabetical, so the order is stable."""
    tables = sorted(tables)
    wanted = set(tables)
    graph: dict[str, set[str]] = {t: set() for t in tables}
    for child, parent in foreign_keys:
        if child in wanted and parent in wanted and child != parent:
            graph[child].add(parent)
    sorter = TopologicalSorter(graph)
    try:
        sorter.prepare()
    except CycleError as exc:
        raise RestoreError(f"foreign keys form a cycle: {exc.args[1]}") from None
    order: list[str] = []
    while sorter.is_active():
        ready = sorted(sorter.get_ready())
        order.extend(ready)
        sorter.done(*ready)
    return order


def foreign_keys(cur: psycopg.Cursor) -> list[tuple[str, str]]:
    cur.execute(_FOREIGN_KEYS)
    return [
        (child.split(".")[-1], parent.split(".")[-1])
        for child, parent in cur.fetchall()
    ]


def count(cur: psycopg.Cursor, table: str) -> int:
    cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table)))
    return cur.fetchone()[0]


# --- the restore ---------------------------------------------------------------------


@dataclass
class TableResult:
    table: str
    rows: int


@dataclass
class RestoreResult:
    tables: list[TableResult]
    sequences: int
    size_bytes: int
    checks_passed: int


def _copy_table(
    source: psycopg.Connection,
    target: psycopg.Connection,
    table: str,
    cols: Sequence[str],
) -> None:
    column_list = sql.SQL(", ").join(sql.Identifier(c) for c in cols)
    out_sql = sql.SQL("COPY {} ({}) TO STDOUT").format(
        sql.Identifier(table), column_list
    )
    in_sql = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(table), column_list
    )
    with (
        source.cursor() as src,
        target.cursor() as dst,
        src.copy(out_sql) as reader,
        dst.copy(in_sql) as writer,
    ):
        for block in reader:
            writer.write(block)


def _sync_sequences(
    source: psycopg.Connection, target: psycopg.Connection, tables: Sequence[str]
) -> int:
    """Carry each column sequence's position over, so new rows don't collide."""
    synced = 0
    with source.cursor() as src, target.cursor() as dst:
        for table in tables:
            for column in columns(src, table):
                src.execute(
                    "SELECT pg_get_serial_sequence(%s, %s)", (f"public.{table}", column)
                )
                sequence = src.fetchone()[0]
                if sequence is None:
                    continue
                src.execute(
                    sql.SQL("SELECT last_value, is_called FROM {}").format(
                        sql.Identifier(*sequence.split("."))
                    )
                )
                last_value, is_called = src.fetchone()
                dst.execute(
                    "SELECT setval(%s, %s, %s)", (sequence, last_value, is_called)
                )
                synced += 1
    return synced


def restore(
    source: psycopg.Connection,
    target: psycopg.Connection,
    *,
    replace: bool = False,
    guard: SizeGuard | None = None,
    checks: Sequence[Check] = CHECKS,
) -> RestoreResult:
    """Copy every data table from ``source`` to ``target`` in one transaction.
    Raises RestoreError (rolled back) for anything that doesn't check out."""
    guard = guard or SizeGuard(WARN_BYTES, REFUSE_BYTES)
    # One consistent snapshot of the source for the whole copy.
    source.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
    source.read_only = True
    with source.transaction(), target.transaction():
        with source.cursor() as src, target.cursor() as dst:
            source_rev, target_rev = revision(src), revision(dst)
            if target_rev is None:
                raise RestoreError(
                    "the target has no schema: run `alembic upgrade head` on it first"
                )
            if source_rev != target_rev:
                raise RestoreError(
                    f"schema revisions differ (source {source_rev}, target "
                    f"{target_rev}): migrate both to the same revision"
                )
            tables = data_tables(src)
            missing = sorted(set(tables) - set(data_tables(dst)))
            if missing:
                raise RestoreError(
                    f"tables missing on the target: {', '.join(missing)}"
                )
            for table in tables:
                if columns(src, table) != columns(dst, table):
                    raise RestoreError(
                        f"table {table} has different columns on the target"
                    )
            order = load_order(tables, foreign_keys(src))

            non_empty = [t for t in order if count(dst, t)]
            if non_empty and not replace:
                raise RestoreError(
                    f"the target already has data in {', '.join(non_empty)}: "
                    "use --replace to overwrite it"
                )
            if non_empty:
                dst.execute(
                    sql.SQL("TRUNCATE {} RESTART IDENTITY").format(
                        sql.SQL(", ").join(sql.Identifier(t) for t in order)
                    )
                )
                logger.info("Emptied %d tables on the target", len(order))
            guard.check(target, "before restoring")

        results = []
        for table in order:
            with source.cursor() as src:
                cols = columns(src, table)
            _copy_table(source, target, table, cols)
            with source.cursor() as src, target.cursor() as dst:
                expected, copied = count(src, table), count(dst, table)
            if copied != expected:
                raise RestoreError(
                    f"{table}: copied {copied} rows, the source has {expected}"
                )
            results.append(TableResult(table, copied))
            logger.info("%-24s %10s rows", table, f"{copied:,}")

        sequences = _sync_sequences(source, target, order)
        size = guard.check(target, "before committing the restore")
        with target.cursor() as dst:
            outcomes = run_checks(dst, checks)
        failed = [c for c in outcomes if not c.passed and not c.skipped]
        if failed:
            raise RestoreError(
                f"{len(failed)} sanity checks failed on the target: "
                + "; ".join(c.describe() for c in failed[:3])
            )
        passed = sum(c.passed for c in outcomes)
    # Committed. Fresh statistics, so the planner uses the indexes at once.
    with target.cursor() as dst:
        for table in order:
            dst.execute(sql.SQL("ANALYZE {}").format(sql.Identifier(table)))
    target.commit()
    return RestoreResult(results, sequences, size, passed)
