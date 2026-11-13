"""ORM models. Importing this package registers every table on `Base.metadata`."""

from app.db.models.f1 import (
    Circuit,
    Constructor,
    ConstructorStanding,
    Driver,
    DriverStanding,
    PitStop,
    Qualifying,
    Race,
    Result,
    Season,
    SprintResult,
    Status,
)

__all__ = [
    "Circuit",
    "Constructor",
    "ConstructorStanding",
    "Driver",
    "DriverStanding",
    "PitStop",
    "Qualifying",
    "Race",
    "Result",
    "Season",
    "SprintResult",
    "Status",
]
