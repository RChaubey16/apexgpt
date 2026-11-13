"""Per-table change counts reported by the loader."""

from dataclasses import dataclass


@dataclass
class TableReport:
    inserted: int = 0
    updated: int = 0
    deleted: int = 0
