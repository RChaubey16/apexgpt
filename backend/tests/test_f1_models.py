"""Unit tests for the structured F1 schema definition (no database needed)."""

import pytest
from sqlalchemy import (
    BigInteger,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    Table,
    UniqueConstraint,
)

from app.db import models  # noqa: F401  (registers tables)
from app.db.base import Base

F1_TABLES = {
    "seasons",
    "circuits",
    "drivers",
    "constructors",
    "status",
    "races",
    "results",
    "sprint_results",
    "qualifying",
    "driver_standings",
    "constructor_standings",
    "pit_stops",
    "driver_aliases",
    "constructor_aliases",
    "constructor_lineage",
}

# Columns that hold small bounded numbers: must be smallint (DATA-STRATEGY §1).
SMALLINT_COLUMNS = {
    "position",
    "position_order",
    "grid",
    "laps",
    "round",
    "season",
    "wins",
    "stop",
    "lap",
    "number",
    "fastest_lap_rank",
    "fastest_lap_number",
}

# Entities cited in answers keep their Wikipedia URL.
TABLES_WITH_WIKIPEDIA_URL = {"seasons", "circuits", "drivers", "constructors", "races"}


def _f1_tables() -> list[Table]:
    return [t for name, t in Base.metadata.tables.items() if name in F1_TABLES]


def test_all_planned_tables_are_defined() -> None:
    assert set(Base.metadata.tables) >= F1_TABLES


def test_lap_times_is_deferred() -> None:
    assert "lap_times" not in Base.metadata.tables


@pytest.mark.parametrize("table", _f1_tables(), ids=lambda t: t.name)
def test_no_redundant_text_columns(table: Table) -> None:
    assert not [c.name for c in table.columns if c.name.endswith("_text")]


@pytest.mark.parametrize("table", _f1_tables(), ids=lambda t: t.name)
def test_compact_types(table: Table) -> None:
    for column in table.columns:
        assert not isinstance(column.type, BigInteger), column
        if column.name in SMALLINT_COLUMNS:
            assert isinstance(column.type, SmallInteger), column
        if column.name == "points":
            assert isinstance(column.type, Numeric), column
            assert (column.type.precision, column.type.scale) == (6, 2), column
        if column.name.endswith("_ms"):
            assert type(column.type) is Integer, column


@pytest.mark.parametrize("name", sorted(TABLES_WITH_WIKIPEDIA_URL))
def test_entities_keep_wikipedia_url(name: str) -> None:
    assert "wikipedia_url" in Base.metadata.tables[name].columns


@pytest.mark.parametrize("table", _f1_tables(), ids=lambda t: t.name)
def test_every_foreign_key_is_indexed(table: Table) -> None:
    """Each FK column leads some index, PK or unique constraint (fast joins)."""
    leading = {idx.columns[0].name for idx in table.indexes}
    leading |= {
        next(iter(c.columns)).name
        for c in table.constraints
        if isinstance(c, PrimaryKeyConstraint | UniqueConstraint)
    }

    # Small lookup tables (status, seasons, circuits) don't need reverse indexes
    # from the big tables, except races.circuit_id which is indexed explicitly.
    exempt = {"status_id", "season"}
    for fk in table.foreign_keys:
        if fk.parent.name in exempt:
            continue
        assert (
            fk.parent.name in leading
        ), f"{table.name}.{fk.parent.name} is not indexed"
