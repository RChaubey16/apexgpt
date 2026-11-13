"""Load transformed F1 data into Postgres: idempotent, atomic sync.

Everything runs in ONE transaction, so a failure leaves the database unchanged:

1. Each table's rows are COPYed into a temporary staging table.
2. Races in the loaded season range that are no longer in the dump are deleted
   (their results, standings, etc. go with them via ON DELETE CASCADE).
3. Rows are upserted parents-first (INSERT ... ON CONFLICT DO UPDATE), touching
   only rows whose values changed.
4. Stale fact rows (results, qualifying, ...) of races in range are deleted.

Entities (drivers, constructors, circuits, seasons, status) are only ever
inserted or updated, never deleted: later tables (aliases, lineage) refer to
them, and an unreferenced entity is harmless. Rows outside the loaded season
range are never touched.

Aliases and constructor lineage (structured/aliases.py) are synced last, in
the same transaction, when seeds are passed.

The schema must already exist (backend migrations: `alembic upgrade head`).
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass

import psycopg
from psycopg import sql

from structured.aliases import Seeds, sync_seeds
from structured.report import TableReport
from structured.transform import F1Data, Record

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TableSpec:
    name: str
    columns: tuple[str, ...]
    key: tuple[str, ...]
    # Fact tables are synced (stale rows deleted) per race in the season range.
    per_race: bool = False


ENTITY_TABLES = (
    TableSpec("seasons", ("year", "wikipedia_url"), ("year",)),
    TableSpec(
        "circuits",
        (
            "circuit_id",
            "ref",
            "name",
            "locality",
            "country",
            "lat",
            "lng",
            "altitude",
            "wikipedia_url",
        ),
        ("circuit_id",),
    ),
    TableSpec(
        "drivers",
        (
            "driver_id",
            "ref",
            "code",
            "number",
            "forename",
            "surname",
            "date_of_birth",
            "nationality",
            "wikipedia_url",
        ),
        ("driver_id",),
    ),
    TableSpec(
        "constructors",
        ("constructor_id", "ref", "name", "nationality", "wikipedia_url"),
        ("constructor_id",),
    ),
)

RACES = TableSpec(
    "races",
    ("race_id", "season", "round", "name", "circuit_id", "date", "wikipedia_url"),
    ("race_id",),
)

_RESULT_COLUMNS = (
    "race_id",
    "driver_id",
    "constructor_id",
    "number",
    "grid",
    "position",
    "position_order",
    "points",
    "laps",
    "time_ms",
    "fastest_lap_number",
    "fastest_lap_ms",
    "status_id",
)

FACT_TABLES = (
    TableSpec(
        "results",
        ("result_id", *_RESULT_COLUMNS, "fastest_lap_rank"),
        ("result_id",),
        True,
    ),
    TableSpec(
        "sprint_results",
        ("sprint_result_id", *_RESULT_COLUMNS),
        ("sprint_result_id",),
        True,
    ),
    TableSpec(
        "qualifying",
        (
            "race_id",
            "driver_id",
            "constructor_id",
            "number",
            "position",
            "q1_ms",
            "q2_ms",
            "q3_ms",
        ),
        ("race_id", "driver_id"),
        True,
    ),
    TableSpec(
        "driver_standings",
        ("race_id", "driver_id", "points", "position", "wins"),
        ("race_id", "driver_id"),
        True,
    ),
    TableSpec(
        "constructor_standings",
        ("race_id", "constructor_id", "points", "position", "wins"),
        ("race_id", "constructor_id"),
        True,
    ),
    TableSpec(
        "pit_stops",
        ("race_id", "driver_id", "stop", "lap", "local_time", "duration_ms"),
        ("race_id", "driver_id", "stop"),
        True,
    ),
)


def _staging(table: str) -> sql.Identifier:
    return sql.Identifier(f"stg_{table}")


def _stage(cur: psycopg.Cursor, spec: TableSpec, rows: Sequence[Record]) -> None:
    cols = sql.SQL(", ").join(map(sql.Identifier, spec.columns))
    cur.execute(
        sql.SQL(
            "CREATE TEMP TABLE {} ON COMMIT DROP AS SELECT {} FROM {} WITH NO DATA"
        ).format(_staging(spec.name), cols, sql.Identifier(spec.name))
    )
    with cur.copy(
        sql.SQL("COPY {} ({}) FROM STDIN").format(_staging(spec.name), cols)
    ) as copy:
        for row in rows:
            copy.write_row(tuple(row[c] for c in spec.columns))


def _upsert(cur: psycopg.Cursor, spec: TableSpec) -> TableReport:
    cols = sql.SQL(", ").join(map(sql.Identifier, spec.columns))
    updatable = [c for c in spec.columns if c not in spec.key]
    target = sql.Identifier(spec.name)
    query = sql.SQL(
        "INSERT INTO {target} AS t ({cols}) SELECT {cols} FROM {stg} "
        "ON CONFLICT ({key}) DO UPDATE SET {sets} "
        "WHERE ({old}) IS DISTINCT FROM ({new}) "
        "RETURNING (xmax = 0)"
    ).format(
        target=target,
        cols=cols,
        stg=_staging(spec.name),
        key=sql.SQL(", ").join(map(sql.Identifier, spec.key)),
        sets=sql.SQL(", ").join(
            sql.SQL("{c} = EXCLUDED.{c}").format(c=sql.Identifier(c)) for c in updatable
        ),
        old=sql.SQL(", ").join(
            sql.SQL("t.{}").format(sql.Identifier(c)) for c in updatable
        ),
        new=sql.SQL(", ").join(
            sql.SQL("EXCLUDED.{}").format(sql.Identifier(c)) for c in updatable
        ),
    )
    cur.execute(query)
    flags = [inserted for (inserted,) in cur.fetchall()]
    return TableReport(inserted=sum(flags), updated=len(flags) - sum(flags))


def _key_match(spec: TableSpec) -> sql.Composable:
    return sql.SQL(" AND ").join(
        sql.SQL("s.{c} = t.{c}").format(c=sql.Identifier(c)) for c in spec.key
    )


def _delete_stale_races(cur: psycopg.Cursor, first: int, last: int) -> int:
    cur.execute(
        sql.SQL(
            "DELETE FROM races t WHERE t.season BETWEEN %s AND %s "
            "AND NOT EXISTS (SELECT 1 FROM {stg} s WHERE {match})"
        ).format(stg=_staging("races"), match=_key_match(RACES)),
        (first, last),
    )
    return cur.rowcount


def _delete_stale_facts(
    cur: psycopg.Cursor, spec: TableSpec, first: int, last: int
) -> int:
    cur.execute(
        sql.SQL(
            "DELETE FROM {target} t "
            "WHERE t.race_id IN (SELECT race_id FROM races WHERE season BETWEEN %s AND %s) "
            "AND NOT EXISTS (SELECT 1 FROM {stg} s WHERE {match})"
        ).format(
            target=sql.Identifier(spec.name),
            stg=_staging(spec.name),
            match=_key_match(spec),
        ),
        (first, last),
    )
    return cur.rowcount


def _sync_statuses(
    cur: psycopg.Cursor, statuses: Sequence[str]
) -> tuple[TableReport, dict[str, int]]:
    cur.execute(
        "INSERT INTO status (status) SELECT unnest(%s::text[]) ON CONFLICT (status) DO NOTHING",
        (list(statuses),),
    )
    report = TableReport(inserted=cur.rowcount)
    cur.execute("SELECT status, status_id FROM status")
    return report, dict(cur.fetchall())


def _with_status_ids(
    rows: Sequence[Record], status_ids: dict[str, int]
) -> list[Record]:
    return [
        {
            **{k: v for k, v in row.items() if k != "status"},
            "status_id": status_ids[row["status"]],
        }
        for row in rows
    ]


def load(
    conn: psycopg.Connection,
    data: F1Data,
    first_season: int,
    last_season: int,
    seeds: Seeds | None = None,
) -> dict[str, TableReport]:
    """Sync the database to `data` for seasons [first_season, last_season], atomically.

    With `seeds`, aliases and lineage are synced too, in the same transaction.
    """
    reports: dict[str, TableReport] = {}
    with conn.transaction(), conn.cursor() as cur:
        status_report, status_ids = _sync_statuses(cur, data.statuses)
        reports["status"] = status_report

        fact_rows: dict[str, list[Record]] = {
            "results": _with_status_ids(data.results, status_ids),
            "sprint_results": _with_status_ids(data.sprint_results, status_ids),
            "qualifying": data.qualifying,
            "driver_standings": data.driver_standings,
            "constructor_standings": data.constructor_standings,
            "pit_stops": data.pit_stops,
        }
        for spec in ENTITY_TABLES:
            _stage(cur, spec, getattr(data, spec.name))
        _stage(cur, RACES, data.races)
        for spec in FACT_TABLES:
            _stage(cur, spec, fact_rows[spec.name])

        # Stale races go first, so a renumbered round can't clash on (season, round).
        deleted_races = _delete_stale_races(cur, first_season, last_season)
        for spec in ENTITY_TABLES:
            reports[spec.name] = _upsert(cur, spec)
        reports["races"] = _upsert(cur, RACES)
        reports["races"].deleted = deleted_races
        for spec in FACT_TABLES:
            report = _upsert(cur, spec)
            report.deleted = _delete_stale_facts(cur, spec, first_season, last_season)
            reports[spec.name] = report
        if seeds is not None:
            reports.update(sync_seeds(cur, seeds))

    for name, r in reports.items():
        logger.info(
            "%-22s +%d inserted  ~%d updated  -%d deleted",
            name,
            r.inserted,
            r.updated,
            r.deleted,
        )
    return reports


def connect(database_url: str, connect_timeout: int) -> psycopg.Connection:
    return psycopg.connect(
        database_url,
        connect_timeout=connect_timeout,
        application_name="apexgpt-ingestion",
        # Safe behind Neon's PgBouncer pooler (transaction mode).
        prepare_threshold=None,
    )
