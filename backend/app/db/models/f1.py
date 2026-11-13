"""Structured Formula 1 data (1950 onwards), loaded from the Jolpica-F1 dump (F1.2).

Design rules (docs/DATA-STRATEGY.md §1):
- Compact types: `smallint` for positions/grid/laps/rounds, `int` for IDs,
  `numeric(6,2)` for points (shared drives in the 1950s award half points).
- No redundant columns: no text duplicates of numeric fields (no `position_text`);
  times are stored once, as integer milliseconds.
- Each entity keeps its Wikipedia URL for citations.
- `lap_times` is deferred to the Live Season phase.

Most primary keys are the source's IDs (assigned by the loader, not generated),
so reloads are idempotent upserts; `status` and `qualifying` have no single
source ID and upsert on their unique keys instead. Check constraints
reject obviously bad data at the boundary.
"""

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    REAL,
    CheckConstraint,
    Date,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Points for one result (max 50) or a season standing (max ever 575).
Points = Numeric(6, 2)


class Season(Base):
    __tablename__ = "seasons"
    __table_args__ = (CheckConstraint("year BETWEEN 1950 AND 2100", name="year_range"),)

    year: Mapped[int] = mapped_column(
        SmallInteger, primary_key=True, autoincrement=False
    )
    wikipedia_url: Mapped[str | None] = mapped_column(Text)


class Circuit(Base):
    __tablename__ = "circuits"
    __table_args__ = (
        CheckConstraint("lat BETWEEN -90 AND 90", name="lat_range"),
        CheckConstraint("lng BETWEEN -180 AND 180", name="lng_range"),
    )

    circuit_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=False
    )
    # Stable slug, e.g. "silverstone".
    ref: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    locality: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    lat: Mapped[float | None] = mapped_column(REAL)
    lng: Mapped[float | None] = mapped_column(REAL)
    # Metres above sea level.
    altitude: Mapped[int | None] = mapped_column(SmallInteger)
    wikipedia_url: Mapped[str | None] = mapped_column(Text)


class Driver(Base):
    __tablename__ = "drivers"
    __table_args__ = (
        CheckConstraint("char_length(code) = 3", name="code_length"),
        CheckConstraint("number BETWEEN 0 AND 999", name="number_range"),
    )

    driver_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=False
    )
    # Stable slug, e.g. "hamilton", "michael_schumacher".
    ref: Mapped[str] = mapped_column(Text, unique=True)
    # Three-letter abbreviation, e.g. "HAM" (modern drivers only).
    code: Mapped[str | None] = mapped_column(String(3))
    # Permanent car number (2014 onwards).
    number: Mapped[int | None] = mapped_column(SmallInteger)
    forename: Mapped[str] = mapped_column(Text)
    surname: Mapped[str] = mapped_column(Text)
    date_of_birth: Mapped[dt.date | None] = mapped_column(Date)
    nationality: Mapped[str | None] = mapped_column(Text)
    wikipedia_url: Mapped[str | None] = mapped_column(Text)


class Constructor(Base):
    __tablename__ = "constructors"

    constructor_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=False
    )
    # Stable slug, e.g. "mercedes", "red_bull".
    ref: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    nationality: Mapped[str | None] = mapped_column(Text)
    wikipedia_url: Mapped[str | None] = mapped_column(Text)


class Status(Base):
    """Finishing status text, e.g. "Finished", "+1 Lap", "Engine", "Accident"."""

    __tablename__ = "status"

    # Generated: the source has status text only. Reloads upsert on `status`.
    status_id: Mapped[int] = mapped_column(SmallInteger, Identity(), primary_key=True)
    status: Mapped[str] = mapped_column(Text, unique=True)


class Race(Base):
    """A championship Grand Prix (one per season round)."""

    __tablename__ = "races"
    __table_args__ = (
        UniqueConstraint("season", "round"),
        CheckConstraint("round >= 1", name="round_positive"),
        Index(None, "circuit_id"),
    )

    race_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    season: Mapped[int] = mapped_column(SmallInteger, ForeignKey("seasons.year"))
    round: Mapped[int] = mapped_column(SmallInteger)
    # e.g. "British Grand Prix".
    name: Mapped[str] = mapped_column(Text)
    circuit_id: Mapped[int] = mapped_column(Integer, ForeignKey("circuits.circuit_id"))
    date: Mapped[dt.date] = mapped_column(Date)
    wikipedia_url: Mapped[str | None] = mapped_column(Text)


# Shared by results and sprint_results: constraint name -> SQL.
_RESULT_CHECKS = {
    "grid_valid": "grid >= 0",  # 0 = started from the pit lane
    "position_valid": "position >= 1",
    "position_order_valid": "position_order >= 1",
    "points_valid": "points >= 0",
    "laps_valid": "laps >= 0",
    "time_ms_valid": "time_ms > 0",
    "fastest_lap_ms_valid": "fastest_lap_ms > 0",
    "fastest_lap_number_valid": "fastest_lap_number >= 1",
}


def _result_checks() -> tuple[CheckConstraint, ...]:
    return tuple(
        CheckConstraint(sql, name=name) for name, sql in _RESULT_CHECKS.items()
    )


class Result(Base):
    """Grand Prix race results: one row per car entry.

    Not unique per (race, driver): in the 1950s a driver could drive two cars in
    one race, and drivers sharing a car share its position and split its points.
    """

    __tablename__ = "results"
    __table_args__ = (
        *_result_checks(),
        CheckConstraint("fastest_lap_rank >= 1", name="fastest_lap_rank_valid"),
        Index(None, "race_id"),
        Index(None, "driver_id"),
        Index(None, "constructor_id"),
    )

    result_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=False
    )
    race_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("races.race_id", ondelete="CASCADE")
    )
    driver_id: Mapped[int] = mapped_column(Integer, ForeignKey("drivers.driver_id"))
    constructor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("constructors.constructor_id")
    )
    # Car number for this race.
    number: Mapped[int | None] = mapped_column(SmallInteger)
    grid: Mapped[int] = mapped_column(SmallInteger)
    # Classified finishing position; NULL when not classified (retired, DSQ, ...).
    position: Mapped[int | None] = mapped_column(SmallInteger)
    # Order in the final classification, including unclassified cars.
    position_order: Mapped[int] = mapped_column(SmallInteger)
    points: Mapped[Decimal] = mapped_column(Points)
    laps: Mapped[int] = mapped_column(SmallInteger)
    # Total race time; only for cars with a recorded time.
    time_ms: Mapped[int | None] = mapped_column(Integer)
    fastest_lap_rank: Mapped[int | None] = mapped_column(SmallInteger)
    fastest_lap_number: Mapped[int | None] = mapped_column(SmallInteger)
    fastest_lap_ms: Mapped[int | None] = mapped_column(Integer)
    status_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("status.status_id"))


class SprintResult(Base):
    """Sprint race results (2021 onwards): one row per driver per sprint."""

    __tablename__ = "sprint_results"
    __table_args__ = (
        UniqueConstraint("race_id", "driver_id"),
        *_result_checks(),
        Index(None, "driver_id"),
        Index(None, "constructor_id"),
    )

    sprint_result_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=False
    )
    race_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("races.race_id", ondelete="CASCADE")
    )
    driver_id: Mapped[int] = mapped_column(Integer, ForeignKey("drivers.driver_id"))
    constructor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("constructors.constructor_id")
    )
    number: Mapped[int | None] = mapped_column(SmallInteger)
    grid: Mapped[int] = mapped_column(SmallInteger)
    position: Mapped[int | None] = mapped_column(SmallInteger)
    position_order: Mapped[int] = mapped_column(SmallInteger)
    points: Mapped[Decimal] = mapped_column(Points)
    laps: Mapped[int] = mapped_column(SmallInteger)
    time_ms: Mapped[int | None] = mapped_column(Integer)
    fastest_lap_number: Mapped[int | None] = mapped_column(SmallInteger)
    fastest_lap_ms: Mapped[int | None] = mapped_column(Integer)
    status_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("status.status_id"))


class Qualifying(Base):
    """Grand Prix qualifying: one row per driver per race.

    Single-session formats (pre-2006) use only q1_ms; the knockout format
    (2006 onwards) fills q1_ms/q2_ms/q3_ms as far as the driver progressed.
    """

    __tablename__ = "qualifying"
    __table_args__ = (
        UniqueConstraint("race_id", "driver_id"),
        CheckConstraint("position >= 1", name="position_valid"),
        CheckConstraint("q1_ms > 0", name="q1_ms_valid"),
        CheckConstraint("q2_ms > 0", name="q2_ms_valid"),
        CheckConstraint("q3_ms > 0", name="q3_ms_valid"),
        Index(None, "driver_id"),
        Index(None, "constructor_id"),
    )

    # Generated: the source splits qualifying across sessions (Q1/Q2/Q3), so
    # there is no single source ID. Reloads upsert on (race_id, driver_id).
    qualify_id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    race_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("races.race_id", ondelete="CASCADE")
    )
    driver_id: Mapped[int] = mapped_column(Integer, ForeignKey("drivers.driver_id"))
    constructor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("constructors.constructor_id")
    )
    number: Mapped[int | None] = mapped_column(SmallInteger)
    # NULL when the driver set no time and was not classified.
    position: Mapped[int | None] = mapped_column(SmallInteger)
    q1_ms: Mapped[int | None] = mapped_column(Integer)
    q2_ms: Mapped[int | None] = mapped_column(Integer)
    q3_ms: Mapped[int | None] = mapped_column(Integer)


class DriverStanding(Base):
    """Drivers' championship standings after each race."""

    __tablename__ = "driver_standings"
    __table_args__ = (
        CheckConstraint("points >= 0", name="points_valid"),
        CheckConstraint("position >= 1", name="position_valid"),
        CheckConstraint("wins >= 0", name="wins_valid"),
        Index(None, "driver_id"),
    )

    race_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("races.race_id", ondelete="CASCADE"), primary_key=True
    )
    driver_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("drivers.driver_id"), primary_key=True
    )
    points: Mapped[Decimal] = mapped_column(Points)
    # NULL when the driver is excluded from the championship (e.g. Schumacher 1997).
    position: Mapped[int | None] = mapped_column(SmallInteger)
    wins: Mapped[int] = mapped_column(SmallInteger)


class ConstructorStanding(Base):
    """Constructors' championship standings after each race (1958 onwards)."""

    __tablename__ = "constructor_standings"
    __table_args__ = (
        CheckConstraint("points >= 0", name="points_valid"),
        CheckConstraint("position >= 1", name="position_valid"),
        CheckConstraint("wins >= 0", name="wins_valid"),
        Index(None, "constructor_id"),
    )

    race_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("races.race_id", ondelete="CASCADE"), primary_key=True
    )
    constructor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("constructors.constructor_id"), primary_key=True
    )
    points: Mapped[Decimal] = mapped_column(Points)
    # NULL when the team is excluded from the championship (e.g. McLaren 2007).
    position: Mapped[int | None] = mapped_column(SmallInteger)
    wins: Mapped[int] = mapped_column(SmallInteger)


class PitStop(Base):
    """Race pit stops (2011 onwards)."""

    __tablename__ = "pit_stops"
    __table_args__ = (
        CheckConstraint("stop >= 1", name="stop_valid"),
        CheckConstraint("lap >= 1", name="lap_valid"),
        CheckConstraint("duration_ms > 0", name="duration_valid"),
        Index(None, "driver_id"),
    )

    race_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("races.race_id", ondelete="CASCADE"), primary_key=True
    )
    driver_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("drivers.driver_id"), primary_key=True
    )
    stop: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    lap: Mapped[int] = mapped_column(SmallInteger)
    # Local time of day at the circuit.
    local_time: Mapped[dt.time | None] = mapped_column(Time)
    # Time in the pit lane (entry to exit), not stationary time.
    duration_ms: Mapped[int] = mapped_column(Integer)
