"""Sync data/narrative/chunks.jsonl into the `chunks` table, embedding only what changed.

A chunk is identified by (pageid, chunk_index); its `content_hash` (model +
embedded text) says whether a stored embedding is still current:

1. Plan: read every stored (key, hash). Chunks whose hash is stored at the same
   key keep their embedding, ones whose hash is stored at another key (an
   article gained or lost a chunk before them) copy it, and the rest are new
   and get embedded. Unknown ids are refused before anything is written.
2. Write in batches, one transaction each (INSERT ... ON CONFLICT DO UPDATE,
   touching only rows that changed), so an interrupted run keeps its progress
   and a re-run embeds only what is left.
3. Delete stored chunks that are no longer in the file, last, once every
   batch is in.

The schema must exist (backend migrations: `alembic upgrade head`) and the
structured data must be loaded (chunks refer to seasons, races and circuits).
"""

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import psycopg
from psycopg import sql

from narrative.chunks import ChunkRecord
from narrative.embedder import Embedder, content_hash
from narrative.errors import SelectionError

logger = logging.getLogger(__name__)

BATCH_SIZE = 256

COLUMNS = (
    "pageid",
    "chunk_index",
    "title",
    "section",
    "text",
    "tokens",
    "source_url",
    "revid",
    "depth",
    "kinds",
    "season",
    "race_id",
    "circuit_id",
    "driver_ids",
    "constructor_ids",
    "topic",
    "content_hash",
    "embedding",
)
KEY = ("pageid", "chunk_index")


class StoreError(SelectionError):
    """The chunks can't be stored (schema missing, unknown ids, bad embeddings)."""


Key = tuple[int, int]


@dataclass(frozen=True)
class _Row:
    chunk: ChunkRecord
    hash: str
    # None: keep the embedding already stored under this key.
    embedding: str | None


@dataclass
class SyncPlan:
    """What a sync will do; built from the stored hashes, before any write."""

    keep: list[_Row]  # stored at this key with this hash: no embedding needed
    copy: list[_Row]  # hash stored under another key: embedding copied
    embed: list[tuple[ChunkRecord, str]]  # new text: needs embedding
    delete: list[Key]  # stored, no longer in the file

    @property
    def total(self) -> int:
        return len(self.keep) + len(self.copy) + len(self.embed)


@dataclass(frozen=True)
class SyncReport:
    chunks: int
    embedded: int
    copied: int
    written: int  # rows inserted or changed
    deleted: int
    truncated: int  # embedded texts longer than the model reads
    table_bytes: int


def vector_literal(vector: Sequence[float], dimensions: int) -> str:
    if len(vector) != dimensions:
        raise StoreError(
            f"embedding has {len(vector)} dimensions, expected {dimensions}"
        )
    return "[" + ",".join(f"{x:.7g}" for x in vector) + "]"


def _check_schema(conn: psycopg.Connection) -> None:
    row = conn.execute("SELECT to_regclass('public.chunks') IS NOT NULL").fetchone()
    if not row or not row[0]:
        raise StoreError(
            "the chunks table does not exist: run the backend migrations first "
            "(`cd backend && uv run alembic upgrade head`)"
        )


def _check_ids(conn: psycopg.Connection, chunks: Sequence[ChunkRecord]) -> None:
    """Every referenced id must exist in the structured data."""
    wanted = {
        ("seasons", "year"): {c.season for c in chunks if c.season is not None},
        ("races", "race_id"): {c.race_id for c in chunks if c.race_id is not None},
        ("circuits", "circuit_id"): {
            c.circuit_id for c in chunks if c.circuit_id is not None
        },
        ("drivers", "driver_id"): {d for c in chunks for d in c.driver_ids},
        ("constructors", "constructor_id"): {
            i for c in chunks for i in c.constructor_ids
        },
    }
    problems = []
    for (table, column), ids in wanted.items():
        if not ids:
            continue
        query = sql.SQL("SELECT {c} FROM {t} WHERE {c} = ANY(%s)").format(
            c=sql.Identifier(column), t=sql.Identifier(table)
        )
        found = {row[0] for row in conn.execute(query, (sorted(ids),))}
        if missing := sorted(ids - found):
            shown = ", ".join(map(str, missing[:10]))
            problems.append(f"{len(missing)} {table} ({shown})")
    if problems:
        raise StoreError(
            "chunks refer to ids missing from the structured data: "
            + "; ".join(problems)
            + ". Load the structured data first (`uv run python -m structured`)"
        )


def plan_sync(
    conn: psycopg.Connection, chunks: Sequence[ChunkRecord], model_name: str
) -> SyncPlan:
    _check_schema(conn)
    keys = [(c.pageid, c.index) for c in chunks]
    if len(set(keys)) != len(keys):
        raise StoreError("chunks.jsonl has duplicate (pageid, index) pairs")
    _check_ids(conn, chunks)

    stored: dict[Key, str] = {
        (pageid, index): digest
        for pageid, index, digest in conn.execute(
            "SELECT pageid, chunk_index, content_hash FROM chunks"
        )
    }
    keep: list[_Row] = []
    moved: list[tuple[ChunkRecord, str]] = []
    embed: list[tuple[ChunkRecord, str]] = []
    stored_hashes = set(stored.values())
    for chunk in chunks:
        digest = content_hash(model_name, chunk.embedding_text)
        if stored.get((chunk.pageid, chunk.index)) == digest:
            keep.append(_Row(chunk, digest, None))
        elif digest in stored_hashes:
            moved.append((chunk, digest))
        else:
            embed.append((chunk, digest))

    vectors: dict[str, str] = {}
    if moved:
        vectors = dict(
            conn.execute(
                "SELECT DISTINCT ON (content_hash) content_hash, embedding::text "
                "FROM chunks WHERE content_hash = ANY(%s)",
                (sorted({digest for _, digest in moved}),),
            ).fetchall()
        )
    copy = [_Row(chunk, digest, vectors[digest]) for chunk, digest in moved]
    wanted = set(keys)
    delete = sorted(key for key in stored if key not in wanted)
    return SyncPlan(keep=keep, copy=copy, embed=embed, delete=delete)


def _values(row: _Row) -> tuple[object, ...]:
    c = row.chunk
    return (
        c.pageid,
        c.index,
        c.title,
        " > ".join(c.section) or None,
        c.text,
        c.tokens,
        c.source_url,
        c.revid,
        c.depth.value,
        [k.value for k in c.kinds],
        c.season,
        c.race_id,
        c.circuit_id,
        list(c.driver_ids),
        list(c.constructor_ids),
        c.topic,
        row.hash,
        row.embedding,
    )


def _write(conn: psycopg.Connection, rows: Sequence[_Row]) -> int:
    """Upsert one batch in its own transaction; returns rows inserted or changed."""
    columns = sql.SQL(", ").join(map(sql.Identifier, COLUMNS))
    updates = [c for c in COLUMNS if c not in KEY]
    with conn.transaction():
        conn.execute(
            "CREATE TEMP TABLE IF NOT EXISTS chunks_staging "
            "(LIKE chunks INCLUDING DEFAULTS) ON COMMIT DELETE ROWS"
        )
        conn.execute("ALTER TABLE chunks_staging ALTER COLUMN embedding DROP NOT NULL")
        with conn.cursor().copy(
            sql.SQL("COPY chunks_staging ({}) FROM STDIN").format(columns)
        ) as copy:
            for row in rows:
                copy.write_row(_values(row))
        # A staged NULL embedding means "keep the stored one": it is filled in
        # before the insert (NOT NULL is checked before ON CONFLICT applies).
        selected = sql.SQL(", ").join(
            sql.SQL(
                "COALESCE(s.embedding, (SELECT c.embedding FROM chunks c "
                "WHERE c.pageid = s.pageid AND c.chunk_index = s.chunk_index))"
                if c == "embedding"
                else "s.{}"
            ).format(sql.Identifier(c))
            for c in COLUMNS
        )
        # content_hash stands for the embedding (same hash, same vector).
        compared = [c for c in updates if c != "embedding"]
        statement = sql.SQL(
            "INSERT INTO chunks ({columns}) SELECT {selected} FROM chunks_staging s "
            "ON CONFLICT (pageid, chunk_index) DO UPDATE SET {sets} "
            "WHERE ({old}) IS DISTINCT FROM ({new})"
        ).format(
            columns=columns,
            selected=selected,
            sets=sql.SQL(", ").join(
                sql.SQL("{c} = EXCLUDED.{c}").format(c=sql.Identifier(c))
                for c in updates
            ),
            old=sql.SQL(", ").join(
                sql.SQL("chunks.{}").format(sql.Identifier(c)) for c in compared
            ),
            new=sql.SQL(", ").join(
                sql.SQL("EXCLUDED.{}").format(sql.Identifier(c)) for c in compared
            ),
        )
        return conn.execute(statement).rowcount


def sync_chunks(
    conn: psycopg.Connection,
    plan: SyncPlan,
    embedder: Embedder,
    *,
    batch_size: int = BATCH_SIZE,
    progress: Callable[[int, int, float], None] | None = None,
) -> SyncReport:
    """Carry out a plan from `plan_sync` (same connection, nothing written in between)."""
    if embedder.dimensions <= 0 or batch_size <= 0:
        raise ValueError("dimensions and batch_size must be positive")
    written = 0
    unchanged = plan.keep + plan.copy
    for start in range(0, len(unchanged), batch_size):
        written += _write(conn, unchanged[start : start + batch_size])

    truncated = 0
    started = time.monotonic()
    for start in range(0, len(plan.embed), batch_size):
        batch = plan.embed[start : start + batch_size]
        texts = [chunk.embedding_text for chunk, _ in batch]
        truncated += embedder.truncated(texts)
        vectors = embedder.embed(texts)
        if len(vectors) != len(batch):
            raise StoreError(f"got {len(vectors)} embeddings for {len(batch)} texts")
        written += _write(
            conn,
            [
                _Row(chunk, digest, vector_literal(vector, embedder.dimensions))
                for (chunk, digest), vector in zip(batch, vectors, strict=True)
            ],
        )
        if progress is not None:
            progress(start + len(batch), len(plan.embed), time.monotonic() - started)

    with conn.transaction():
        deleted = 0
        if plan.delete:
            deleted = conn.execute(
                "DELETE FROM chunks c USING unnest(%s::int[], %s::int[]) AS d(p, i) "
                "WHERE c.pageid = d.p AND c.chunk_index = d.i",
                ([p for p, _ in plan.delete], [i for _, i in plan.delete]),
            ).rowcount
        count, size = conn.execute(
            "SELECT count(*), pg_total_relation_size('chunks') FROM chunks"
        ).fetchone() or (0, 0)
    if count != plan.total:
        raise StoreError(
            f"the chunks table has {count} rows after the sync, expected {plan.total} "
            "(changed by another process?)"
        )
    return SyncReport(
        chunks=plan.total,
        embedded=len(plan.embed),
        copied=len(plan.copy),
        written=written,
        deleted=deleted,
        truncated=truncated,
        table_bytes=size,
    )
