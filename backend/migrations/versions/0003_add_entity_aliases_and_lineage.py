"""Add entity resolution and team history tables: driver_aliases,
constructor_aliases and constructor_lineage.

Mirrors app/db/models/f1.py; a test fails if the two drift apart.
Rows are synced by the ingestion loader (generated names + curated seeds).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "constructor_aliases",
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("constructor_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "alias ~ '^[a-z0-9]+( [a-z0-9]+)*$'",
            name=op.f("ck_constructor_aliases_alias_format"),
        ),
        sa.CheckConstraint(
            "kind IN ('name', 'nickname')",
            name=op.f("ck_constructor_aliases_kind_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["constructor_id"],
            ["constructors.constructor_id"],
            name=op.f("fk_constructor_aliases_constructor_id_constructors"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "alias", "constructor_id", name=op.f("pk_constructor_aliases")
        ),
    )
    op.create_index(
        op.f("ix_constructor_aliases_constructor_id"),
        "constructor_aliases",
        ["constructor_id"],
        unique=False,
    )
    op.create_table(
        "constructor_lineage",
        sa.Column("predecessor_id", sa.Integer(), nullable=False),
        sa.Column("successor_id", sa.Integer(), nullable=False),
        sa.Column("season", sa.SmallInteger(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "predecessor_id <> successor_id",
            name=op.f("ck_constructor_lineage_distinct_teams"),
        ),
        sa.CheckConstraint(
            "season BETWEEN 1950 AND 2100",
            name=op.f("ck_constructor_lineage_season_range"),
        ),
        sa.ForeignKeyConstraint(
            ["predecessor_id"],
            ["constructors.constructor_id"],
            name=op.f("fk_constructor_lineage_predecessor_id_constructors"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["successor_id"],
            ["constructors.constructor_id"],
            name=op.f("fk_constructor_lineage_successor_id_constructors"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "predecessor_id",
            "successor_id",
            "season",
            name=op.f("pk_constructor_lineage"),
        ),
    )
    op.create_index(
        op.f("ix_constructor_lineage_successor_id"),
        "constructor_lineage",
        ["successor_id"],
        unique=False,
    )
    op.create_table(
        "driver_aliases",
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "alias ~ '^[a-z0-9]+( [a-z0-9]+)*$'",
            name=op.f("ck_driver_aliases_alias_format"),
        ),
        sa.CheckConstraint(
            "kind IN ('name', 'surname', 'nickname')",
            name=op.f("ck_driver_aliases_kind_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["driver_id"],
            ["drivers.driver_id"],
            name=op.f("fk_driver_aliases_driver_id_drivers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("alias", "driver_id", name=op.f("pk_driver_aliases")),
    )
    op.create_index(
        op.f("ix_driver_aliases_driver_id"),
        "driver_aliases",
        ["driver_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_driver_aliases_driver_id"), table_name="driver_aliases")
    op.drop_table("driver_aliases")
    op.drop_index(
        op.f("ix_constructor_lineage_successor_id"), table_name="constructor_lineage"
    )
    op.drop_table("constructor_lineage")
    op.drop_index(
        op.f("ix_constructor_aliases_constructor_id"), table_name="constructor_aliases"
    )
    op.drop_table("constructor_aliases")
