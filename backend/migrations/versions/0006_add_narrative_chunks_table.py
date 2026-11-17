"""Add the narrative corpus table: chunks (Wikipedia text + bge-small embeddings).

Mirrors app/db/models/narrative.py; a test fails if the two drift apart.
- embedding: halfvec(384) with an HNSW index (halfvec_cosine_ops)
- full-text search: GIN index on to_tsvector('english', title || ' ' || text),
  no stored tsvector column
Rows are synced by the ingestion pipeline (`python -m narrative.embed`).

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import HALFVEC

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Same expression as app/db/models/narrative.py (CHUNK_TSVECTOR).
# Written as Postgres prints it, so Alembic sees no difference; queries may
# write `title || ' ' || text` (the same expression) and still use the index.
TSVECTOR = "to_tsvector('english'::regconfig, (title || ' '::text) || text)"


def upgrade() -> None:
    op.create_table(
        "chunks",
        sa.Column("pageid", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.SmallInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("section", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("tokens", sa.SmallInteger(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("revid", sa.Integer(), nullable=False),
        sa.Column("depth", sa.Text(), nullable=False),
        sa.Column("kinds", sa.ARRAY(sa.Text()), nullable=False),
        sa.Column("season", sa.SmallInteger(), nullable=True),
        sa.Column("race_id", sa.Integer(), nullable=True),
        sa.Column("circuit_id", sa.Integer(), nullable=True),
        sa.Column("driver_ids", sa.ARRAY(sa.Integer()), nullable=False),
        sa.Column("constructor_ids", sa.ARRAY(sa.Integer()), nullable=False),
        sa.Column("topic", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("embedding", HALFVEC(dim=384), nullable=False),
        sa.CheckConstraint(
            "depth IN ('full', 'race', 'circuit', 'lead')",
            name=op.f("ck_chunks_depth_valid"),
        ),
        sa.CheckConstraint(
            "chunk_index >= 0", name=op.f("ck_chunks_index_non_negative")
        ),
        sa.CheckConstraint(
            "length(content_hash) = 32", name=op.f("ck_chunks_content_hash_format")
        ),
        sa.CheckConstraint("length(text) > 0", name=op.f("ck_chunks_text_not_empty")),
        sa.CheckConstraint("tokens > 0", name=op.f("ck_chunks_tokens_positive")),
        sa.ForeignKeyConstraint(
            ["circuit_id"],
            ["circuits.circuit_id"],
            name=op.f("fk_chunks_circuit_id_circuits"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["race_id"],
            ["races.race_id"],
            name=op.f("fk_chunks_race_id_races"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["season"],
            ["seasons.year"],
            name=op.f("fk_chunks_season_seasons"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("pageid", "chunk_index", name=op.f("pk_chunks")),
    )
    op.create_index(
        "ix_chunks_embedding_hnsw",
        "chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "halfvec_cosine_ops"},
    )
    op.create_index(
        "ix_chunks_tsvector",
        "chunks",
        [sa.literal_column(TSVECTOR)],
        unique=False,
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_chunks_tsvector", table_name="chunks")
    op.drop_index("ix_chunks_embedding_hnsw", table_name="chunks")
    op.drop_table("chunks")
