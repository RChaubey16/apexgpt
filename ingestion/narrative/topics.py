"""Read and validate the curated topic list (narrative/topics.yaml).

The file maps a topic group to a list of articles:

    rivalry:
      - title: Prost–Senna rivalry
        drivers: [prost, senna]          # driver refs (structured data)
        constructors: [mclaren]          # constructor refs
        season: 1989                     # one season, if the topic is about one
        circuit: suzuka                  # circuit ref

Only `title` is required. Refs are checked against the database when the
selection is built; titles are checked against Wikipedia when it's resolved.
"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from narrative.errors import SelectionError
from narrative.wiki import validate_title

TOPICS_FILE = Path(__file__).resolve().parent / "topics.yaml"
MAX_FILE_BYTES = 1_000_000
FIRST_SEASON = 1950
LAST_SEASON = 2025
_REF = r"^[a-z0-9_\-]+$"


class Group(StrEnum):
    RIVALRY = "rivalry"
    SAFETY = "safety"  # fatal accidents, major crashes, safety changes
    CONTROVERSY = "controversy"
    ICONIC_RACE = "iconic_race"  # famous races and title deciders
    REGULATIONS = "regulations"  # rules and technical eras
    CAR = "car"  # landmark cars
    CONCEPT = "concept"  # how the sport works (flags, safety car, DRS, ...)
    PEOPLE = "people"  # team bosses, designers, officials, commentators
    HISTORY = "history"  # the sport and its organisations


class _Entry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str
    drivers: tuple[str, ...] = ()
    constructors: tuple[str, ...] = ()
    season: int | None = Field(default=None, ge=FIRST_SEASON, le=LAST_SEASON)
    circuit: str | None = Field(default=None, pattern=_REF)

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        return validate_title(value)

    @field_validator("drivers", "constructors")
    @classmethod
    def _refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for ref in value:
            if not re.fullmatch(_REF, ref):
                raise ValueError(f"invalid ref {ref!r}")
        if len(set(value)) != len(value):
            raise ValueError("refs are listed twice")
        return value


class Topic(_Entry):
    group: Group


def parse_topics(data: Any, source: str = "topics.yaml") -> list[Topic]:
    """Validate the parsed YAML document; raises SelectionError on any problem."""
    if not isinstance(data, dict) or not data:
        raise SelectionError(f"{source}: expected a mapping of topic group -> list")
    problems: list[str] = []
    topics: list[Topic] = []
    seen: dict[str, str] = {}
    for group_name, entries in data.items():
        try:
            group = Group(group_name)
        except ValueError:
            known = ", ".join(g.value for g in Group)
            problems.append(f"unknown group {group_name!r} (known: {known})")
            continue
        if not isinstance(entries, list) or not entries:
            problems.append(f"{group_name}: expected a non-empty list of entries")
            continue
        for i, raw in enumerate(entries, start=1):
            where = f"{group_name}[{i}]"
            try:
                entry = _Entry.model_validate(raw)
            except ValidationError as exc:
                for err in exc.errors():
                    field = ".".join(str(p) for p in err["loc"]) or "entry"
                    problems.append(f"{where} {field}: {err['msg']}")
                continue
            if entry.title in seen:
                problems.append(
                    f"{where}: {entry.title!r} is already listed ({seen[entry.title]})"
                )
                continue
            seen[entry.title] = where
            topics.append(Topic(**entry.model_dump(), group=group))
    if problems:
        raise SelectionError(f"{source} is invalid:\n  " + "\n  ".join(problems))
    return topics


def read_topics(path: Path = TOPICS_FILE) -> list[Topic]:
    try:
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise SelectionError(f"{path.name} is unexpectedly large ({size} bytes)")
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SelectionError(
            f"cannot read {path.name}: {exc.strerror or type(exc).__name__}"
        ) from None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 1})" if mark is not None else ""
        raise SelectionError(f"{path.name} is not valid YAML{where}") from None
    return parse_topics(data, path.name)
