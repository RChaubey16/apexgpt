"""Chunk sync against a real Postgres + pgvector (see test_load.py for setup notes).

A fake embedder stands in for the model: deterministic unit vectors from a hash
of the text, with a call log, so tests can see exactly what was embedded.
"""

import hashlib
import logging
import math
import os
from collections.abc import Iterator, Sequence
from pathlib import Path

import psycopg
import pytest

from narrative import embed as cli
from narrative.chunks import ChunkRecord, chunks_path, write_chunks
from narrative.embedder import MODEL_NAME
from narrative.selection import Depth, Kind
from narrative.store import StoreError, SyncReport, plan_sync, sync_chunks
from structured.config import Settings, normalise_database_url
from structured.load import load
from structured.transform import transform
from tests.fixture_dump import FakeSource
from tests.integration.test_load import F1_TABLES, migrated  # noqa: F401  (fixture)

pytestmark = pytest.mark.integration

_RAW_URL = os.environ.get("TEST_DATABASE_URL")
if not _RAW_URL:
    pytest.skip("TEST_DATABASE_URL not set", allow_module_level=True)
DATABASE_URL = normalise_database_url(_RAW_URL)
DIMS = 384


class FakeEmbedder:
    model_name = MODEL_NAME
    dimensions = DIMS

    def __init__(self, fail_after: int | None = None) -> None:
        self.embedded: list[str] = []
        self.fail_after = fail_after

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if self.fail_after is not None and len(self.embedded) >= self.fail_after:
            raise RuntimeError("model crashed")
        self.embedded.extend(texts)
        return [vector(t) for t in texts]

    def truncated(self, texts: Sequence[str]) -> int:
        return sum("LONG" in t for t in texts)


def vector(text: str) -> list[float]:
    seed = hashlib.sha256(text.encode()).digest()
    raw = [(seed[i % 32] - 127.5) * (1 + i % 7) for i in range(DIMS)]
    norm = math.sqrt(sum(x * x for x in raw))
    return [x / norm for x in raw]


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute(f"TRUNCATE {', '.join(F1_TABLES)} RESTART IDENTITY CASCADE")
        connection.execute("TRUNCATE chunks")
        load(connection, transform(FakeSource()), 1950, 2025)
        yield connection


@pytest.fixture
def ids(conn: psycopg.Connection) -> dict[str, int]:
    def one(query: str) -> int:
        row = conn.execute(query).fetchone()
        assert row is not None
        return int(row[0])

    return {
        "race": one("SELECT race_id FROM races ORDER BY race_id LIMIT 1"),
        "circuit": one("SELECT circuit_id FROM circuits ORDER BY circuit_id LIMIT 1"),
        "driver": one("SELECT driver_id FROM drivers ORDER BY driver_id LIMIT 1"),
        "constructor": one(
            "SELECT constructor_id FROM constructors ORDER BY constructor_id LIMIT 1"
        ),
    }


def chunk(pageid: int, index: int, text: str, **extra: object) -> ChunkRecord:
    fields: dict[str, object] = {
        "pageid": pageid,
        "index": index,
        "title": f"Article {pageid}",
        "revid": 1,
        "source_url": f"https://en.wikipedia.org/?curid={pageid}",
        "section": ("Race",) if index else (),
        "text": text,
        "tokens": 10,
        "depth": Depth.FULL,
        "kinds": (Kind.TOPIC,),
    }
    return ChunkRecord.model_validate(fields | extra)


def sync(
    conn: psycopg.Connection,
    chunks: Sequence[ChunkRecord],
    embedder: FakeEmbedder | None = None,
    batch_size: int = 256,
) -> tuple[SyncReport, FakeEmbedder]:
    embedder = embedder or FakeEmbedder()
    plan = plan_sync(conn, chunks, MODEL_NAME)
    return sync_chunks(conn, plan, embedder, batch_size=batch_size), embedder


def stored(conn: psycopg.Connection) -> dict[tuple[int, int], tuple]:
    return {
        (r[0], r[1]): r[2:]
        for r in conn.execute(
            "SELECT pageid, chunk_index, text, revid, section FROM chunks"
        )
    }


def test_first_sync_embeds_and_stores_everything(
    conn: psycopg.Connection, ids: dict[str, int]
) -> None:
    chunks = [
        chunk(
            1,
            0,
            "Senna and Prost collided at Suzuka.",
            season=2021,
            race_id=ids["race"],
            circuit_id=ids["circuit"],
            driver_ids=(ids["driver"],),
            constructor_ids=(ids["constructor"],),
            topic="rivalry",
            kinds=(Kind.RACE, Kind.TOPIC),
            depth=Depth.RACE,
        ),
        chunk(1, 1, "The race restarted after a LONG delay."),
        chunk(2, 0, "Monaco is a street circuit."),
    ]

    report, embedder = sync(conn, chunks)

    assert (report.chunks, report.embedded, report.written, report.deleted) == (
        3,
        3,
        3,
        0,
    )
    assert report.truncated == 1
    assert report.table_bytes > 0
    assert embedder.embedded == [c.embedding_text for c in chunks]
    row = conn.execute(
        "SELECT title, section, depth, kinds, season, race_id, circuit_id, driver_ids, "
        "constructor_ids, topic, source_url, tokens, length(content_hash) "
        "FROM chunks WHERE pageid = 1 AND chunk_index = 0"
    ).fetchone()
    assert row == (
        "Article 1",
        None,
        "race",
        ["race", "topic"],
        2021,
        ids["race"],
        ids["circuit"],
        [ids["driver"]],
        [ids["constructor"]],
        "rivalry",
        "https://en.wikipedia.org/?curid=1",
        10,
        32,
    )
    assert conn.execute(
        "SELECT section FROM chunks WHERE pageid = 1 AND chunk_index = 1"
    ).fetchone() == ("Race",)


def test_vectors_are_searchable(conn: psycopg.Connection) -> None:
    chunks = [chunk(1, 0, "Senna and Prost collided."), chunk(2, 0, "Monaco rain.")]
    sync(conn, chunks)

    query = "[" + ",".join(map(str, vector(chunks[1].embedding_text))) + "]"
    conn.execute("SET enable_seqscan = off")  # use the HNSW index
    nearest = conn.execute(
        "SELECT pageid, embedding <=> %s::halfvec AS distance FROM chunks "
        "ORDER BY embedding <=> %s::halfvec LIMIT 1",
        (query, query),
    ).fetchone()
    conn.execute("RESET enable_seqscan")
    assert nearest is not None
    assert nearest[0] == 2
    assert nearest[1] < 0.001  # halfvec rounding only


def test_full_text_search_matches_title_and_text(conn: psycopg.Connection) -> None:
    sync(
        conn,
        [
            chunk(
                1,
                0,
                "Senna and Prost collided at the chicane.",
                title="1989 Japanese Grand Prix",
            ),
            chunk(2, 0, "Monaco is a street circuit."),
        ],
    )

    def search(q: str) -> list[int]:
        return [
            r[0]
            for r in conn.execute(
                "SELECT pageid FROM chunks WHERE to_tsvector('english'::regconfig, "
                "title || ' ' || text) @@ websearch_to_tsquery('english', %s)",
                (q,),
            )
        ]

    assert search("collision Senna Prost") == []  # "collided" ≠ "collision" stem
    assert search("Senna Prost collided") == [1]
    assert search("Japanese chicane") == [1]  # title words count too
    conn.execute("SET enable_seqscan = off")
    plan = conn.execute(
        "EXPLAIN SELECT pageid FROM chunks WHERE to_tsvector('english'::regconfig, "
        "title || ' ' || text) @@ websearch_to_tsquery('english', 'Senna')"
    ).fetchall()
    conn.execute("RESET enable_seqscan")
    assert "ix_chunks_tsvector" in " ".join(r[0] for r in plan)


def test_a_second_sync_embeds_and_writes_nothing(conn: psycopg.Connection) -> None:
    chunks = [chunk(1, 0, "Lead."), chunk(1, 1, "Race.")]
    sync(conn, chunks)

    report, embedder = sync(conn, chunks)

    assert (report.embedded, report.written, report.deleted) == (0, 0, 0)
    assert embedder.embedded == []


def test_only_changed_text_is_embedded(conn: psycopg.Connection) -> None:
    sync(conn, [chunk(1, 0, "Lead."), chunk(1, 1, "Race.")])

    report, embedder = sync(conn, [chunk(1, 0, "Lead."), chunk(1, 1, "Race, edited.")])

    assert embedder.embedded == [chunk(1, 1, "Race, edited.").embedding_text]
    assert (report.embedded, report.written) == (1, 1)
    assert stored(conn)[(1, 1)][0] == "Race, edited."


def test_metadata_changes_are_written_without_embedding(
    conn: psycopg.Connection,
) -> None:
    sync(conn, [chunk(1, 0, "Lead.")])
    before = conn.execute("SELECT embedding::text FROM chunks").fetchone()

    report, embedder = sync(conn, [chunk(1, 0, "Lead.", revid=2, topic="safety")])

    assert embedder.embedded == []
    assert report.written == 1
    assert conn.execute(
        "SELECT revid, topic, embedding::text FROM chunks"
    ).fetchone() == (
        2,
        "safety",
        before[0] if before else None,
    )


def test_shifted_chunks_reuse_their_embeddings(conn: psycopg.Connection) -> None:
    sync(conn, [chunk(1, 0, "Lead."), chunk(1, 1, "Race."), chunk(1, 2, "Aftermath.")])
    old = dict(conn.execute("SELECT text, embedding::text FROM chunks").fetchall())

    # A new chunk at index 1 moves "Race." and "Aftermath." down one.
    shifted = [
        chunk(1, 0, "Lead."),
        chunk(1, 1, "Background."),
        chunk(1, 2, "Race."),
        chunk(1, 3, "Aftermath."),
    ]
    report, embedder = sync(conn, shifted, batch_size=1)

    assert embedder.embedded == [shifted[1].embedding_text]
    assert (report.embedded, report.copied) == (1, 2)
    new = dict(conn.execute("SELECT text, embedding::text FROM chunks").fetchall())
    assert new["Race."] == old["Race."]
    assert new["Aftermath."] == old["Aftermath."]
    assert len(stored(conn)) == 4


def test_chunks_no_longer_in_the_file_are_deleted(conn: psycopg.Connection) -> None:
    sync(conn, [chunk(1, 0, "Lead."), chunk(1, 1, "Race."), chunk(2, 0, "Other.")])

    report, _ = sync(conn, [chunk(1, 0, "Lead.")])

    assert report.deleted == 2
    assert set(stored(conn)) == {(1, 0)}


def test_an_interrupted_sync_keeps_its_progress(conn: psycopg.Connection) -> None:
    chunks = [chunk(1, i, f"Paragraph {i}.") for i in range(5)]
    with pytest.raises(RuntimeError, match="model crashed"):
        sync(conn, chunks, FakeEmbedder(fail_after=2), batch_size=2)
    assert len(stored(conn)) == 2

    report, embedder = sync(conn, chunks, batch_size=2)

    assert embedder.embedded == [c.embedding_text for c in chunks[2:]]
    assert report.embedded == 3
    assert len(stored(conn)) == 5


def test_unknown_ids_are_refused_before_writing(
    conn: psycopg.Connection, ids: dict[str, int]
) -> None:
    chunks = [
        chunk(1, 0, "Lead.", race_id=999_999, driver_ids=(ids["driver"], 888_888)),
        chunk(2, 0, "Other.", season=1949),
    ]

    with pytest.raises(StoreError) as exc:
        sync(conn, chunks)

    message = str(exc.value)
    assert "1 seasons (1949)" in message
    assert "1 races (999999)" in message
    assert "1 drivers (888888)" in message
    assert "Load the structured data first" in message
    assert stored(conn) == {}


def test_duplicate_keys_are_refused(conn: psycopg.Connection) -> None:
    with pytest.raises(StoreError, match="duplicate"):
        sync(conn, [chunk(1, 0, "A."), chunk(1, 0, "B.")])


def test_wrong_dimensions_are_refused(conn: psycopg.Connection) -> None:
    class Short(FakeEmbedder):
        def embed(self, texts: Sequence[str]) -> list[list[float]]:
            return [[0.1, 0.2] for _ in texts]

    with pytest.raises(StoreError, match="2 dimensions, expected 384"):
        sync(conn, [chunk(1, 0, "A.")], Short())
    assert stored(conn) == {}


def test_deleting_a_race_keeps_its_chunks(
    conn: psycopg.Connection, ids: dict[str, int]
) -> None:
    sync(conn, [chunk(1, 0, "Lead.", race_id=ids["race"])])

    conn.execute("DELETE FROM races WHERE race_id = %s", (ids["race"],))

    assert conn.execute("SELECT race_id FROM chunks").fetchone() == (None,)


def test_cli_end_to_end(
    conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    write_chunks(chunks_path(tmp_path), [chunk(1, 0, "Lead."), chunk(1, 1, "Race.")])
    embedder = FakeEmbedder()
    monkeypatch.setattr(cli, "_load_embedder", lambda settings: embedder)
    caplog.set_level(logging.INFO)

    assert cli.run(["--dry-run"]) == 0
    assert (
        "2 chunks: 0 unchanged, 0 moved (embedding reused), 2 to embed" in caplog.text
    )
    assert stored(conn) == {}

    assert cli.run([]) == 0
    assert (
        "Synced 2 chunks: 2 embedded, 0 moved, 2 rows written, 0 deleted" in caplog.text
    )
    assert len(stored(conn)) == 2

    # Nothing to embed: the model is never loaded.
    monkeypatch.setattr(cli, "_load_embedder", lambda settings: pytest.fail("loaded"))
    assert cli.run([]) == 0


def test_cli_reports_a_missing_table(
    conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    write_chunks(chunks_path(tmp_path), [chunk(1, 0, "Lead.")])
    conn.execute("ALTER TABLE chunks RENAME TO chunks_hidden")
    try:
        assert cli.run([]) == 1
    finally:
        conn.execute("ALTER TABLE chunks_hidden RENAME TO chunks")
    assert "the chunks table does not exist" in caplog.text


def test_a_table_changed_during_the_sync_is_reported(conn: psycopg.Connection) -> None:
    sync(conn, [chunk(1, 0, "Lead.")])
    plan = plan_sync(conn, [chunk(1, 0, "Lead.")], MODEL_NAME)
    # Another writer adds a row after the plan was made.
    conn.execute(
        "INSERT INTO chunks SELECT 2, chunk_index, title, section, text, tokens, "
        "source_url, revid, depth, kinds, season, race_id, circuit_id, driver_ids, "
        "constructor_ids, topic, content_hash, embedding FROM chunks"
    )

    with pytest.raises(StoreError, match="has 2 rows after the sync, expected 1"):
        sync_chunks(conn, plan, FakeEmbedder())
