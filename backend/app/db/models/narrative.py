"""Narrative corpus: Wikipedia chunks with embeddings (F2.5).

Design rules (docs/DATA-STRATEGY.md §2c):
- `halfvec(384)` embeddings (bge-small-en-v1.5, 16-bit) with an HNSW cosine index.
- Full-text search uses a GIN index on an expression; no stored tsvector column.
  Queries must use the same expression (`CHUNK_TSVECTOR`) for the index to apply.
- Metadata are the structured data's integer IDs, so retrieval can filter by them.
- Raw articles are not stored; `source_url` + `revid` are kept for attribution.

Rows are synced by the ingestion pipeline (`python -m narrative.embed`):
(pageid, chunk_index) identifies a chunk, and `content_hash` (model + embedded
text) tells it which embeddings are still current.
"""

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

EMBEDDING_DIMENSIONS = 384
# The text full-text search matches: the article title, then the chunk.
# Written as Postgres prints it, so Alembic sees no difference; queries may
# write `title || ' ' || text` (the same expression) and still use the index.
CHUNK_TSVECTOR = "to_tsvector('english'::regconfig, (title || ' '::text) || text)"
DEPTHS = ("full", "race", "circuit", "lead")


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        CheckConstraint("chunk_index >= 0", name="index_non_negative"),
        CheckConstraint("tokens > 0", name="tokens_positive"),
        CheckConstraint("length(text) > 0", name="text_not_empty"),
        CheckConstraint(
            "depth IN (" + ", ".join(f"'{d}'" for d in DEPTHS) + ")",
            name="depth_valid",
        ),
        CheckConstraint("length(content_hash) = 32", name="content_hash_format"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "halfvec_cosine_ops"},
        ),
        Index("ix_chunks_tsvector", text(CHUNK_TSVECTOR), postgresql_using="gin"),
    )

    # Wikipedia page id + position in the article.
    pageid: Mapped[int] = mapped_column(Integer, primary_key=True)
    chunk_index: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    # Heading path joined with " > "; NULL for the article's lead.
    section: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    # Estimated tokens, including the "title > section" heading.
    tokens: Mapped[int] = mapped_column(SmallInteger)
    source_url: Mapped[str] = mapped_column(Text)
    revid: Mapped[int] = mapped_column(Integer)
    depth: Mapped[str] = mapped_column(Text)
    # Kinds of article (season, race, driver, constructor, circuit, topic).
    kinds: Mapped[list[str]] = mapped_column(ARRAY(Text))
    season: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("seasons.year", ondelete="SET NULL")
    )
    race_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("races.race_id", ondelete="SET NULL")
    )
    circuit_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("circuits.circuit_id", ondelete="SET NULL")
    )
    # Arrays can't carry foreign keys; the pipeline checks they exist.
    driver_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer))
    constructor_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer))
    topic: Mapped[str | None] = mapped_column(Text)
    # Hex BLAKE2b-128 of the embedding model + embedded text: unchanged → keep embedding.
    content_hash: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(HALFVEC(EMBEDDING_DIMENSIONS))
