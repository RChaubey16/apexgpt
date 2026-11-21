"""Fold accents in chunk full-text search ("Nurburgring" matches "Nürburgring").

- enables the `unaccent` extension (trusted since Postgres 13, so the database
  owner can create it; available on Neon)
- adds the text search configuration `apex_english`: English stemming with
  unaccent applied first, so accents are folded in documents and queries alike
- rebuilds ix_chunks_tsvector on to_tsvector('apex_english', title || ' ' || text)

Mirrors app/db/models/narrative.py (CHUNK_TSVECTOR); a test fails if the two
drift apart.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Written as Postgres prints them, so Alembic sees no difference.
NEW_TSVECTOR = "to_tsvector('apex_english'::regconfig, (title || ' '::text) || text)"
OLD_TSVECTOR = "to_tsvector('english'::regconfig, (title || ' '::text) || text)"


def _create_tsvector_index(expression: str) -> None:
    op.create_index(
        "ix_chunks_tsvector",
        "chunks",
        [sa.literal_column(expression)],
        unique=False,
        postgresql_using="gin",
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.execute("CREATE TEXT SEARCH CONFIGURATION apex_english (COPY = english)")
    # The token types english_stem handles; unaccent passes the folded word on.
    op.execute(
        "ALTER TEXT SEARCH CONFIGURATION apex_english "
        "ALTER MAPPING FOR hword, hword_part, word WITH unaccent, english_stem"
    )
    op.drop_index("ix_chunks_tsvector", table_name="chunks")
    _create_tsvector_index(NEW_TSVECTOR)


def downgrade() -> None:
    op.drop_index("ix_chunks_tsvector", table_name="chunks")
    _create_tsvector_index(OLD_TSVECTOR)
    op.execute("DROP TEXT SEARCH CONFIGURATION apex_english")
    op.execute("DROP EXTENSION IF EXISTS unaccent")
