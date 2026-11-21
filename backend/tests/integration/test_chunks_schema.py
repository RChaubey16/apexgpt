"""Integration tests for the narrative chunks table (migration 0006) on real Postgres.

Skipped unless TEST_DATABASE_URL is set (see test_database.py for the warning).
"""

from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, inspect, select, text
from sqlalchemy.exc import DataError, IntegrityError, StatementError
from sqlalchemy.orm import Session

from app.db.models import Chunk
from app.db.models.narrative import CHUNK_TSVECTOR, TS_CONFIG
from tests.integration import test_f1_schema as f1

# The F1 schema tests' rolled-back session and parent rows.
session = f1.session
base_rows = f1.base_rows


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    """A freshly migrated, empty schema (whatever ran before), reset afterwards."""
    command.downgrade(f1._alembic_config(), "base")
    command.upgrade(f1._alembic_config(), "head")
    eng = create_engine(f1.DATABASE_URL, connect_args={"prepare_threshold": None})
    yield eng
    eng.dispose()
    command.downgrade(f1._alembic_config(), "base")


pytestmark = pytest.mark.integration


def _vector(hot: int) -> list[float]:
    return [1.0 if i == hot else 0.0 for i in range(384)]


def _chunk(index: int = 0, **overrides: object) -> Chunk:
    values: dict[str, object] = {
        "pageid": 100,
        "chunk_index": index,
        "title": "1988 Japanese Grand Prix",
        "section": None,
        "text": "Senna stalled on the grid and recovered to win the title.",
        "tokens": 20,
        "source_url": "https://en.wikipedia.org/wiki/1988_Japanese_Grand_Prix",
        "revid": 1,
        "depth": "race",
        "kinds": ["race"],
        "driver_ids": [],
        "constructor_ids": [],
        "content_hash": "0" * 32,
        "embedding": _vector(index),
    }
    return Chunk(**(values | overrides))


def test_upgrade_creates_the_chunks_indexes(engine: Engine) -> None:
    with engine.connect() as conn:
        indexes = dict(
            conn.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'chunks'"
                )
            ).all()
        )

    assert set(indexes) == {
        "pk_chunks",
        "ix_chunks_embedding_hnsw",
        "ix_chunks_tsvector",
    }
    assert (
        "USING hnsw (embedding halfvec_cosine_ops)"
        in indexes["ix_chunks_embedding_hnsw"]
    )
    assert f"USING gin ({CHUNK_TSVECTOR.replace(', (', ', ((')})" in (
        indexes["ix_chunks_tsvector"]
    )
    columns = {c["name"]: c for c in inspect(engine).get_columns("chunks")}
    assert "tsvector" not in {str(c["type"]).lower() for c in columns.values()}
    assert str(columns["embedding"]["type"]) == "HALFVEC(384)"


def test_round_trip_with_links_and_vector_search(
    session: Session, base_rows: dict[str, int]
) -> None:
    session.add_all(
        [
            _chunk(
                0,
                season=1988,
                race_id=base_rows["race_id"],
                circuit_id=1,
                driver_ids=[1, 2],
                constructor_ids=[1],
                topic="iconic_race",
            ),
            _chunk(1, section="Race", text="Prost led early."),
        ]
    )
    session.flush()

    nearest = session.scalars(
        select(Chunk).order_by(Chunk.embedding.cosine_distance(_vector(1))).limit(1)
    ).one()
    assert (nearest.chunk_index, nearest.section) == (1, "Race")
    first = session.get(Chunk, (100, 0))
    assert first is not None
    assert (first.season, first.race_id, first.driver_ids) == (1988, 1, [1, 2])
    assert list(first.embedding)[:2] == [1.0, 0.0]
    matched = session.scalars(
        select(Chunk.chunk_index).where(
            text(
                f"{CHUNK_TSVECTOR} @@ websearch_to_tsquery('{TS_CONFIG}', 'Japanese stall')"
            )
        )
    ).all()
    assert matched == [0]


@pytest.mark.parametrize(
    "overrides",
    [
        {"depth": "partial"},
        {"content_hash": "abc"},
        {"text": ""},
        {"tokens": 0},
        {"chunk_index": -1},
        {"season": 1900},  # no such season
        {"race_id": 999},
    ],
)
def test_bad_chunks_are_rejected(
    session: Session, base_rows: dict[str, int], overrides: dict[str, object]
) -> None:
    session.add(_chunk(**overrides))
    with pytest.raises(IntegrityError):
        session.flush()


@pytest.mark.parametrize(
    "embedding", [[0.1, 0.2], None], ids=["wrong dimensions", "missing"]
)
def test_embedding_must_have_384_dimensions(
    session: Session, base_rows: dict[str, int], embedding: list[float] | None
) -> None:
    session.add(_chunk(embedding=embedding))
    with pytest.raises((DataError, IntegrityError, StatementError, ValueError)):
        session.flush()


def test_downgrade_to_0005_drops_only_chunks(engine: Engine) -> None:
    command.downgrade(f1._alembic_config(), "0005")
    try:
        tables = set(inspect(engine).get_table_names())
        assert "chunks" not in tables
        assert "races" in tables
    finally:
        command.upgrade(f1._alembic_config(), "head")
