"""Add the answer feedback table (F4.3).

Thumbs up/down on an answer: rating, question, answer excerpt (≤ 500 chars)
and the provider/model that answered. Rows older than 90 days are purged
(app/feedback). Not granted to the LLM's read-only role.

Mirrors app/db/models/feedback.py; test_migration_matches_models fails if the
two drift apart.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("rating", sa.Text(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer_excerpt", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "rating IN ('up', 'down')", name=op.f("ck_feedback_rating_valid")
        ),
        sa.CheckConstraint(
            "length(question) BETWEEN 1 AND 500",
            name=op.f("ck_feedback_question_length"),
        ),
        sa.CheckConstraint(
            "length(answer_excerpt) BETWEEN 1 AND 500",
            name=op.f("ck_feedback_answer_excerpt_length"),
        ),
        sa.CheckConstraint(
            "length(provider) <= 40", name=op.f("ck_feedback_provider_length")
        ),
        sa.CheckConstraint(
            "length(model) <= 200", name=op.f("ck_feedback_model_length")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback")),
    )
    op.create_index("ix_feedback_created_at", "feedback", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_feedback_created_at", table_name="feedback")
    op.drop_table("feedback")
