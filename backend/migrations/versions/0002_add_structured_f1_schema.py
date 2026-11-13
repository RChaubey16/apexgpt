"""Add the structured F1 schema (seasons, circuits, drivers, constructors,
races, results, sprint results, qualifying, standings, pit stops, status).

Mirrors app/db/models/f1.py; a test fails if the two drift apart.
`lap_times` is deliberately absent (deferred, see docs/DATA-STRATEGY.md).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "circuits",
        sa.Column("circuit_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("ref", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("locality", sa.Text(), nullable=True),
        sa.Column("country", sa.Text(), nullable=True),
        sa.Column("lat", sa.REAL(), nullable=True),
        sa.Column("lng", sa.REAL(), nullable=True),
        sa.Column("altitude", sa.SmallInteger(), nullable=True),
        sa.Column("wikipedia_url", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "lat BETWEEN -90 AND 90", name=op.f("ck_circuits_lat_range")
        ),
        sa.CheckConstraint(
            "lng BETWEEN -180 AND 180", name=op.f("ck_circuits_lng_range")
        ),
        sa.PrimaryKeyConstraint("circuit_id", name=op.f("pk_circuits")),
        sa.UniqueConstraint("ref", name=op.f("uq_circuits_ref")),
    )
    op.create_table(
        "constructors",
        sa.Column("constructor_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("ref", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("nationality", sa.Text(), nullable=True),
        sa.Column("wikipedia_url", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("constructor_id", name=op.f("pk_constructors")),
        sa.UniqueConstraint("ref", name=op.f("uq_constructors_ref")),
    )
    op.create_table(
        "drivers",
        sa.Column("driver_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("ref", sa.Text(), nullable=False),
        sa.Column("code", sa.String(length=3), nullable=True),
        sa.Column("number", sa.SmallInteger(), nullable=True),
        sa.Column("forename", sa.Text(), nullable=False),
        sa.Column("surname", sa.Text(), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("nationality", sa.Text(), nullable=True),
        sa.Column("wikipedia_url", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "char_length(code) = 3", name=op.f("ck_drivers_code_length")
        ),
        sa.CheckConstraint(
            "number BETWEEN 0 AND 999", name=op.f("ck_drivers_number_range")
        ),
        sa.PrimaryKeyConstraint("driver_id", name=op.f("pk_drivers")),
        sa.UniqueConstraint("ref", name=op.f("uq_drivers_ref")),
    )
    op.create_table(
        "seasons",
        sa.Column("year", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("wikipedia_url", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "year BETWEEN 1950 AND 2100", name=op.f("ck_seasons_year_range")
        ),
        sa.PrimaryKeyConstraint("year", name=op.f("pk_seasons")),
    )
    op.create_table(
        "status",
        sa.Column(
            "status_id", sa.SmallInteger(), sa.Identity(always=False), nullable=False
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("status_id", name=op.f("pk_status")),
        sa.UniqueConstraint("status", name=op.f("uq_status_status")),
    )
    op.create_table(
        "races",
        sa.Column("race_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("season", sa.SmallInteger(), nullable=False),
        sa.Column("round", sa.SmallInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("circuit_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("wikipedia_url", sa.Text(), nullable=True),
        sa.CheckConstraint("round >= 1", name=op.f("ck_races_round_positive")),
        sa.ForeignKeyConstraint(
            ["circuit_id"],
            ["circuits.circuit_id"],
            name=op.f("fk_races_circuit_id_circuits"),
        ),
        sa.ForeignKeyConstraint(
            ["season"], ["seasons.year"], name=op.f("fk_races_season_seasons")
        ),
        sa.PrimaryKeyConstraint("race_id", name=op.f("pk_races")),
        sa.UniqueConstraint("season", "round", name=op.f("uq_races_season")),
    )
    op.create_index(op.f("ix_races_circuit_id"), "races", ["circuit_id"], unique=False)
    op.create_table(
        "constructor_standings",
        sa.Column("race_id", sa.Integer(), nullable=False),
        sa.Column("constructor_id", sa.Integer(), nullable=False),
        sa.Column("points", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=True),
        sa.Column("wins", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint(
            "points >= 0", name=op.f("ck_constructor_standings_points_valid")
        ),
        sa.CheckConstraint(
            "position >= 1", name=op.f("ck_constructor_standings_position_valid")
        ),
        sa.CheckConstraint(
            "wins >= 0", name=op.f("ck_constructor_standings_wins_valid")
        ),
        sa.ForeignKeyConstraint(
            ["constructor_id"],
            ["constructors.constructor_id"],
            name=op.f("fk_constructor_standings_constructor_id_constructors"),
        ),
        sa.ForeignKeyConstraint(
            ["race_id"],
            ["races.race_id"],
            name=op.f("fk_constructor_standings_race_id_races"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "race_id", "constructor_id", name=op.f("pk_constructor_standings")
        ),
    )
    op.create_index(
        op.f("ix_constructor_standings_constructor_id"),
        "constructor_standings",
        ["constructor_id"],
        unique=False,
    )
    op.create_table(
        "driver_standings",
        sa.Column("race_id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column("points", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=True),
        sa.Column("wins", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint(
            "points >= 0", name=op.f("ck_driver_standings_points_valid")
        ),
        sa.CheckConstraint(
            "position >= 1", name=op.f("ck_driver_standings_position_valid")
        ),
        sa.CheckConstraint("wins >= 0", name=op.f("ck_driver_standings_wins_valid")),
        sa.ForeignKeyConstraint(
            ["driver_id"],
            ["drivers.driver_id"],
            name=op.f("fk_driver_standings_driver_id_drivers"),
        ),
        sa.ForeignKeyConstraint(
            ["race_id"],
            ["races.race_id"],
            name=op.f("fk_driver_standings_race_id_races"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "race_id", "driver_id", name=op.f("pk_driver_standings")
        ),
    )
    op.create_index(
        op.f("ix_driver_standings_driver_id"),
        "driver_standings",
        ["driver_id"],
        unique=False,
    )
    op.create_table(
        "pit_stops",
        sa.Column("race_id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column("stop", sa.SmallInteger(), nullable=False),
        sa.Column("lap", sa.SmallInteger(), nullable=False),
        sa.Column("local_time", sa.Time(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.CheckConstraint("duration_ms > 0", name=op.f("ck_pit_stops_duration_valid")),
        sa.CheckConstraint("lap >= 1", name=op.f("ck_pit_stops_lap_valid")),
        sa.CheckConstraint("stop >= 1", name=op.f("ck_pit_stops_stop_valid")),
        sa.ForeignKeyConstraint(
            ["driver_id"],
            ["drivers.driver_id"],
            name=op.f("fk_pit_stops_driver_id_drivers"),
        ),
        sa.ForeignKeyConstraint(
            ["race_id"],
            ["races.race_id"],
            name=op.f("fk_pit_stops_race_id_races"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "race_id", "driver_id", "stop", name=op.f("pk_pit_stops")
        ),
    )
    op.create_index(
        op.f("ix_pit_stops_driver_id"), "pit_stops", ["driver_id"], unique=False
    )
    op.create_table(
        "qualifying",
        sa.Column(
            "qualify_id", sa.Integer(), sa.Identity(always=False), nullable=False
        ),
        sa.Column("race_id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column("constructor_id", sa.Integer(), nullable=False),
        sa.Column("number", sa.SmallInteger(), nullable=True),
        sa.Column("position", sa.SmallInteger(), nullable=True),
        sa.Column("q1_ms", sa.Integer(), nullable=True),
        sa.Column("q2_ms", sa.Integer(), nullable=True),
        sa.Column("q3_ms", sa.Integer(), nullable=True),
        sa.CheckConstraint("position >= 1", name=op.f("ck_qualifying_position_valid")),
        sa.CheckConstraint("q1_ms > 0", name=op.f("ck_qualifying_q1_ms_valid")),
        sa.CheckConstraint("q2_ms > 0", name=op.f("ck_qualifying_q2_ms_valid")),
        sa.CheckConstraint("q3_ms > 0", name=op.f("ck_qualifying_q3_ms_valid")),
        sa.ForeignKeyConstraint(
            ["constructor_id"],
            ["constructors.constructor_id"],
            name=op.f("fk_qualifying_constructor_id_constructors"),
        ),
        sa.ForeignKeyConstraint(
            ["driver_id"],
            ["drivers.driver_id"],
            name=op.f("fk_qualifying_driver_id_drivers"),
        ),
        sa.ForeignKeyConstraint(
            ["race_id"],
            ["races.race_id"],
            name=op.f("fk_qualifying_race_id_races"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("qualify_id", name=op.f("pk_qualifying")),
        sa.UniqueConstraint("race_id", "driver_id", name=op.f("uq_qualifying_race_id")),
    )
    op.create_index(
        op.f("ix_qualifying_driver_id"), "qualifying", ["driver_id"], unique=False
    )
    op.create_index(
        op.f("ix_qualifying_constructor_id"),
        "qualifying",
        ["constructor_id"],
        unique=False,
    )
    op.create_table(
        "results",
        sa.Column("result_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("race_id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column("constructor_id", sa.Integer(), nullable=False),
        sa.Column("number", sa.SmallInteger(), nullable=True),
        sa.Column("grid", sa.SmallInteger(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=True),
        sa.Column("position_order", sa.SmallInteger(), nullable=False),
        sa.Column("points", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("laps", sa.SmallInteger(), nullable=False),
        sa.Column("time_ms", sa.Integer(), nullable=True),
        sa.Column("fastest_lap_rank", sa.SmallInteger(), nullable=True),
        sa.Column("fastest_lap_number", sa.SmallInteger(), nullable=True),
        sa.Column("fastest_lap_ms", sa.Integer(), nullable=True),
        sa.Column("status_id", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint(
            "fastest_lap_ms > 0", name=op.f("ck_results_fastest_lap_ms_valid")
        ),
        sa.CheckConstraint(
            "fastest_lap_number >= 1", name=op.f("ck_results_fastest_lap_number_valid")
        ),
        sa.CheckConstraint(
            "fastest_lap_rank >= 1", name=op.f("ck_results_fastest_lap_rank_valid")
        ),
        sa.CheckConstraint("grid >= 0", name=op.f("ck_results_grid_valid")),
        sa.CheckConstraint("laps >= 0", name=op.f("ck_results_laps_valid")),
        sa.CheckConstraint("points >= 0", name=op.f("ck_results_points_valid")),
        sa.CheckConstraint("position >= 1", name=op.f("ck_results_position_valid")),
        sa.CheckConstraint(
            "position_order >= 1", name=op.f("ck_results_position_order_valid")
        ),
        sa.CheckConstraint("time_ms > 0", name=op.f("ck_results_time_ms_valid")),
        sa.ForeignKeyConstraint(
            ["constructor_id"],
            ["constructors.constructor_id"],
            name=op.f("fk_results_constructor_id_constructors"),
        ),
        sa.ForeignKeyConstraint(
            ["driver_id"],
            ["drivers.driver_id"],
            name=op.f("fk_results_driver_id_drivers"),
        ),
        sa.ForeignKeyConstraint(
            ["race_id"],
            ["races.race_id"],
            name=op.f("fk_results_race_id_races"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["status_id"],
            ["status.status_id"],
            name=op.f("fk_results_status_id_status"),
        ),
        sa.PrimaryKeyConstraint("result_id", name=op.f("pk_results")),
    )
    op.create_index(
        op.f("ix_results_constructor_id"), "results", ["constructor_id"], unique=False
    )
    op.create_index(
        op.f("ix_results_driver_id"), "results", ["driver_id"], unique=False
    )
    op.create_index(op.f("ix_results_race_id"), "results", ["race_id"], unique=False)
    op.create_table(
        "sprint_results",
        sa.Column(
            "sprint_result_id", sa.Integer(), autoincrement=False, nullable=False
        ),
        sa.Column("race_id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column("constructor_id", sa.Integer(), nullable=False),
        sa.Column("number", sa.SmallInteger(), nullable=True),
        sa.Column("grid", sa.SmallInteger(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=True),
        sa.Column("position_order", sa.SmallInteger(), nullable=False),
        sa.Column("points", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("laps", sa.SmallInteger(), nullable=False),
        sa.Column("time_ms", sa.Integer(), nullable=True),
        sa.Column("fastest_lap_number", sa.SmallInteger(), nullable=True),
        sa.Column("fastest_lap_ms", sa.Integer(), nullable=True),
        sa.Column("status_id", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint(
            "fastest_lap_ms > 0", name=op.f("ck_sprint_results_fastest_lap_ms_valid")
        ),
        sa.CheckConstraint(
            "fastest_lap_number >= 1",
            name=op.f("ck_sprint_results_fastest_lap_number_valid"),
        ),
        sa.CheckConstraint("grid >= 0", name=op.f("ck_sprint_results_grid_valid")),
        sa.CheckConstraint("laps >= 0", name=op.f("ck_sprint_results_laps_valid")),
        sa.CheckConstraint("points >= 0", name=op.f("ck_sprint_results_points_valid")),
        sa.CheckConstraint(
            "position >= 1", name=op.f("ck_sprint_results_position_valid")
        ),
        sa.CheckConstraint(
            "position_order >= 1", name=op.f("ck_sprint_results_position_order_valid")
        ),
        sa.CheckConstraint("time_ms > 0", name=op.f("ck_sprint_results_time_ms_valid")),
        sa.ForeignKeyConstraint(
            ["constructor_id"],
            ["constructors.constructor_id"],
            name=op.f("fk_sprint_results_constructor_id_constructors"),
        ),
        sa.ForeignKeyConstraint(
            ["driver_id"],
            ["drivers.driver_id"],
            name=op.f("fk_sprint_results_driver_id_drivers"),
        ),
        sa.ForeignKeyConstraint(
            ["race_id"],
            ["races.race_id"],
            name=op.f("fk_sprint_results_race_id_races"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["status_id"],
            ["status.status_id"],
            name=op.f("fk_sprint_results_status_id_status"),
        ),
        sa.PrimaryKeyConstraint("sprint_result_id", name=op.f("pk_sprint_results")),
        sa.UniqueConstraint(
            "race_id", "driver_id", name=op.f("uq_sprint_results_race_id")
        ),
    )
    op.create_index(
        op.f("ix_sprint_results_constructor_id"),
        "sprint_results",
        ["constructor_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sprint_results_driver_id"),
        "sprint_results",
        ["driver_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_sprint_results_driver_id"), table_name="sprint_results")
    op.drop_index(op.f("ix_sprint_results_constructor_id"), table_name="sprint_results")
    op.drop_table("sprint_results")
    op.drop_index(op.f("ix_results_race_id"), table_name="results")
    op.drop_index(op.f("ix_results_driver_id"), table_name="results")
    op.drop_index(op.f("ix_results_constructor_id"), table_name="results")
    op.drop_table("results")
    op.drop_index(op.f("ix_qualifying_constructor_id"), table_name="qualifying")
    op.drop_index(op.f("ix_qualifying_driver_id"), table_name="qualifying")
    op.drop_table("qualifying")
    op.drop_index(op.f("ix_pit_stops_driver_id"), table_name="pit_stops")
    op.drop_table("pit_stops")
    op.drop_index(op.f("ix_driver_standings_driver_id"), table_name="driver_standings")
    op.drop_table("driver_standings")
    op.drop_index(
        op.f("ix_constructor_standings_constructor_id"),
        table_name="constructor_standings",
    )
    op.drop_table("constructor_standings")
    op.drop_index(op.f("ix_races_circuit_id"), table_name="races")
    op.drop_table("races")
    op.drop_table("status")
    op.drop_table("seasons")
    op.drop_table("drivers")
    op.drop_table("constructors")
    op.drop_table("circuits")
