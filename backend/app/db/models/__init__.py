"""ORM models. Importing this package registers every table on `Base.metadata`."""

from app.db.models.f1 import (
    Circuit,
    Constructor,
    ConstructorAlias,
    ConstructorLineage,
    ConstructorStanding,
    Driver,
    DriverAlias,
    DriverStanding,
    PitStop,
    Qualifying,
    Race,
    Result,
    Season,
    SprintResult,
    Status,
)
from app.db.models.feedback import Feedback
from app.db.models.narrative import Chunk

__all__ = [
    "Chunk",
    "Circuit",
    "Constructor",
    "ConstructorAlias",
    "ConstructorLineage",
    "ConstructorStanding",
    "Driver",
    "DriverAlias",
    "DriverStanding",
    "Feedback",
    "PitStop",
    "Qualifying",
    "Race",
    "Result",
    "Season",
    "SprintResult",
    "Status",
]
