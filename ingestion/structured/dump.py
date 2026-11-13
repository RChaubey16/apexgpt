"""Read tables from the Jolpica CSV dump zip without extracting it to disk.

Columns are addressed by name (Jolpica does not guarantee column order) and
every table's required columns are checked up front, so a schema change in a
future dump fails with a clear message instead of loading wrong data.
"""

import csv
import io
import zipfile
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Protocol

from structured.errors import DumpError

Row = Mapping[str, str]

# Columns the transform reads, per dump table.
REQUIRED_COLUMNS: dict[str, frozenset[str]] = {
    "season": frozenset({"id", "year", "wikipedia"}),
    "circuit": frozenset(
        {
            "id",
            "reference",
            "name",
            "locality",
            "country",
            "latitude",
            "longitude",
            "altitude",
            "wikipedia",
        }
    ),
    "driver": frozenset(
        {
            "id",
            "reference",
            "abbreviation",
            "permanent_car_number",
            "forename",
            "surname",
            "date_of_birth",
            "nationality",
            "wikipedia",
        }
    ),
    "team": frozenset({"id", "reference", "name", "nationality", "wikipedia"}),
    "round": frozenset(
        {
            "id",
            "season_id",
            "number",
            "name",
            "circuit_id",
            "date",
            "is_cancelled",
            "wikipedia",
        }
    ),
    "session": frozenset({"id", "round_id", "number", "type", "is_cancelled"}),
    "teamdriver": frozenset({"id", "driver_id", "team_id"}),
    "roundentry": frozenset({"id", "round_id", "team_driver_id", "car_number"}),
    "sessionentry": frozenset(
        {
            "id",
            "session_id",
            "round_entry_id",
            "position",
            "is_classified",
            "status",
            "detail",
            "points",
            "grid",
            "time",
            "fastest_lap_rank",
            "laps_completed",
        }
    ),
    "lap": frozenset(
        {
            "id",
            "session_entry_id",
            "number",
            "time",
            "is_entry_fastest_lap",
            "is_deleted",
        }
    ),
    "pitstop": frozenset(
        {"session_entry_id", "number", "lap_id", "local_timestamp", "duration"}
    ),
    "driverchampionship": frozenset(
        {
            "driver_id",
            "round_id",
            "points",
            "position",
            "win_count",
            "is_eligible",
            "adjustment_type",
        }
    ),
    "teamchampionship": frozenset(
        {
            "team_id",
            "round_id",
            "points",
            "position",
            "win_count",
            "is_eligible",
            "adjustment_type",
        }
    ),
}

# Zip-bomb guard: the largest table (laps) is ~37 MB uncompressed.
MAX_MEMBER_BYTES = 500_000_000


class TableSource(Protocol):
    """Anything that yields a dump table's rows (the zip, or a fake in tests)."""

    def rows(self, table: str) -> Iterator[Row]: ...


class DumpReader:
    """Reads `formula_one_<table>.csv` members from a Jolpica CSV dump zip."""

    def __init__(self, path: Path) -> None:
        try:
            self._zip = zipfile.ZipFile(path)
        except (zipfile.BadZipFile, OSError) as exc:
            raise DumpError(f"{path.name} is not a readable zip file: {exc}") from None
        self._members = {info.filename: info for info in self._zip.infolist()}

    def close(self) -> None:
        self._zip.close()

    def __enter__(self) -> "DumpReader":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def rows(self, table: str) -> Iterator[Row]:
        name = f"formula_one_{table}.csv"
        info = self._members.get(name)
        if info is None:
            raise DumpError(f"dump has no {name}")
        if info.file_size > MAX_MEMBER_BYTES:
            raise DumpError(f"{name} is unexpectedly large ({info.file_size} bytes)")
        with self._zip.open(info) as raw:
            reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8", newline=""))
            check_columns(table, reader.fieldnames)
            yield from reader


def check_columns(table: str, fieldnames: object) -> None:
    present = set(fieldnames) if isinstance(fieldnames, list | tuple) else set()
    missing = REQUIRED_COLUMNS.get(table, frozenset()) - present
    if missing:
        raise DumpError(
            f"dump table {table!r} is missing columns: {', '.join(sorted(missing))}"
        )
