"""The Jolpica-F1 API (the Ergast successor) for the current season (F8.3).

Three resources, each validated with pydantic before use:

- `{season}.json`: the calendar (rounds, circuits, session times);
- `{season}/driverStandings.json` and `{season}/constructorStandings.json`:
  the standings after the latest round.

`season` is a year or "current". Every failure (network, timeout, HTTP error,
bad JSON, data that doesn't validate, a truncated page) raises `JolpicaError`,
whose message names the resource only: it's logged, never shown to visitors.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

# One page holds a whole season: ~24 rounds, ~25 drivers, ~11 teams.
PAGE_LIMIT = 100
# A season's standings or calendar is ~50 KB; anything far bigger is wrong.
MAX_RESPONSE_BYTES = 2_000_000

SessionKind = Literal[
    "practice_1",
    "practice_2",
    "practice_3",
    "sprint_qualifying",
    "sprint",
    "qualifying",
    "race",
]

# Jolpica's key for each session; 2023 called sprint qualifying a "shootout".
_SESSION_KEYS: tuple[tuple[str, SessionKind], ...] = (
    ("FirstPractice", "practice_1"),
    ("SecondPractice", "practice_2"),
    ("ThirdPractice", "practice_3"),
    ("SprintQualifying", "sprint_qualifying"),
    ("SprintShootout", "sprint_qualifying"),
    ("Sprint", "sprint"),
    ("Qualifying", "qualifying"),
)


class JolpicaError(Exception):
    """Jolpica couldn't be reached or sent data we can't use."""


class _Model(BaseModel):
    # Jolpica adds fields over time; only the ones we read are validated.
    model_config = ConfigDict(extra="ignore", frozen=True)


# --- calendar --------------------------------------------------------------------


class Location(_Model):
    locality: str = Field(min_length=1, max_length=100)
    country: str = Field(min_length=1, max_length=100)


class Circuit(_Model):
    circuit_id: str = Field(alias="circuitId", min_length=1, max_length=100)
    name: str = Field(alias="circuitName", min_length=1, max_length=200)
    location: Location = Field(alias="Location")


class SessionTime(_Model):
    date: dt.date
    # Missing while the timetable isn't published.
    time: dt.time | None = None

    @property
    def start(self) -> dt.datetime | None:
        """The start in UTC, or None while the time isn't published."""
        if self.time is None:
            return None
        clock = self.time if self.time.tzinfo else self.time.replace(tzinfo=dt.UTC)
        return dt.datetime.combine(self.date, clock).astimezone(dt.UTC)


class Race(_Model):
    model_config = ConfigDict(extra="allow", frozen=True)

    season: int = Field(ge=1950, le=2100)
    round: int = Field(ge=1, le=100)
    name: str = Field(alias="raceName", min_length=1, max_length=200)
    url: str | None = Field(default=None, max_length=500)
    circuit: Circuit = Field(alias="Circuit")
    date: dt.date
    time: dt.time | None = None

    @property
    def schedule(self) -> SessionTime:
        return SessionTime(date=self.date, time=self.time)

    def sessions(self) -> list[tuple[SessionKind, SessionTime]]:
        """The weekend's sessions in order, the race last."""
        found: list[tuple[SessionKind, SessionTime]] = []
        extra = self.model_extra or {}
        for key, kind in _SESSION_KEYS:
            if key in extra and extra[key] is not None:
                try:
                    found.append((kind, SessionTime.model_validate(extra[key])))
                except ValidationError:
                    raise JolpicaError(
                        f"bad {key} time in round {self.round}"
                    ) from None
        found.sort(key=lambda item: (item[1].date, _clock(item[1])))
        found.append(("race", self.schedule))
        return found


class _RaceTable(_Model):
    season: int = Field(ge=1950, le=2100)
    races: list[Race] = Field(alias="Races", max_length=PAGE_LIMIT)


# --- standings -------------------------------------------------------------------


class Constructor(_Model):
    constructor_id: str = Field(alias="constructorId", min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    nationality: str | None = Field(default=None, max_length=100)


class Driver(_Model):
    driver_id: str = Field(alias="driverId", min_length=1, max_length=100)
    code: str | None = Field(default=None, max_length=10)
    number: int | None = Field(default=None, alias="permanentNumber", ge=0, le=999)
    given_name: str = Field(alias="givenName", min_length=1, max_length=100)
    family_name: str = Field(alias="familyName", min_length=1, max_length=100)
    nationality: str | None = Field(default=None, max_length=100)


class DriverStanding(_Model):
    # Missing for a driver excluded from the championship (positionText "D").
    position: int | None = Field(default=None, ge=1, le=PAGE_LIMIT)
    position_text: str = Field(alias="positionText", min_length=1, max_length=10)
    points: float = Field(ge=0, le=10_000)
    wins: int = Field(ge=0, le=100)
    driver: Driver = Field(alias="Driver")
    # More than one when a driver changed teams; the last is the latest.
    constructors: list[Constructor] = Field(alias="Constructors", max_length=10)


class ConstructorStanding(_Model):
    position: int | None = Field(default=None, ge=1, le=PAGE_LIMIT)
    position_text: str = Field(alias="positionText", min_length=1, max_length=10)
    points: float = Field(ge=0, le=10_000)
    wins: int = Field(ge=0, le=100)
    constructor: Constructor = Field(alias="Constructor")


class _StandingsList(_Model):
    season: int = Field(ge=1950, le=2100)
    round: int = Field(ge=1, le=100)
    drivers: list[DriverStanding] | None = Field(
        default=None, alias="DriverStandings", max_length=PAGE_LIMIT
    )
    constructors: list[ConstructorStanding] | None = Field(
        default=None, alias="ConstructorStandings", max_length=PAGE_LIMIT
    )


class _StandingsTable(_Model):
    season: int = Field(ge=1950, le=2100)
    lists: list[_StandingsList] = Field(alias="StandingsLists", max_length=1)


# --- what callers get -----------------------------------------------------------


@dataclass(frozen=True)
class Calendar:
    season: int
    races: list[Race]


@dataclass(frozen=True)
class Standings[T]:
    """A season's standings after `round`; round None (no entries) before
    the season's first race."""

    season: int
    round: int | None
    entries: list[T]


# --- the client ------------------------------------------------------------------


class JolpicaClient:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def calendar(self, season: str) -> Calendar | None:
        """The season's races in round order; None when Jolpica doesn't have
        the season (a 404, or no races yet)."""
        data = await self._get(f"{season}.json", allow_missing=True)
        if data is None:
            return None
        table = _parse(_RaceTable, data, "RaceTable", f"{season} calendar")
        if not table.races:
            return None
        races = sorted(table.races, key=lambda race: race.round)
        if len({race.round for race in races}) != len(races):
            raise JolpicaError(f"repeated rounds in the {season} calendar")
        return Calendar(season=table.season, races=races)

    async def driver_standings(self, season: str) -> Standings[DriverStanding]:
        data = await self._get(f"{season}/driverStandings.json")
        table = _parse(_StandingsTable, data, "StandingsTable", f"{season} drivers")
        if not table.lists:
            return Standings(season=table.season, round=None, entries=[])
        page = table.lists[0]
        entries = _ordered(page.drivers or [])
        return Standings(season=page.season, round=page.round, entries=entries)

    async def constructor_standings(
        self, season: str
    ) -> Standings[ConstructorStanding]:
        data = await self._get(f"{season}/constructorStandings.json")
        table = _parse(
            _StandingsTable, data, "StandingsTable", f"{season} constructors"
        )
        if not table.lists:
            return Standings(season=table.season, round=None, entries=[])
        page = table.lists[0]
        entries = _ordered(page.constructors or [])
        return Standings(season=page.season, round=page.round, entries=entries)

    async def _get(self, path: str, *, allow_missing: bool = False) -> dict | None:
        try:
            response = await self._http.get(path, params={"limit": PAGE_LIMIT})
        except httpx.TimeoutException:
            raise JolpicaError(f"timed out fetching {path}") from None
        except httpx.HTTPError as exc:
            raise JolpicaError(
                f"could not fetch {path}: {type(exc).__name__}"
            ) from None
        if response.status_code == 404 and allow_missing:
            return None
        if response.status_code != 200:
            raise JolpicaError(f"HTTP {response.status_code} for {path}")
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise JolpicaError(f"{path} is too large ({len(response.content)} bytes)")
        try:
            body = response.json()
        except ValueError:
            raise JolpicaError(f"{path} is not JSON") from None
        data = body.get("MRData") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            raise JolpicaError(f"{path} has no MRData")
        _check_complete(data, path)
        return data


def _clock(session: SessionTime) -> dt.time:
    """For ordering: an unpublished time sorts after the day's known ones."""
    if session.time is None:
        return dt.time.max
    return session.time.replace(tzinfo=None)


def _check_complete(data: dict, path: str) -> None:
    """A season must fit on one page; a truncated one would drop rows."""
    try:
        total = int(data.get("total", 0))
    except (TypeError, ValueError):
        raise JolpicaError(f"{path} has a bad total") from None
    if total > PAGE_LIMIT:
        raise JolpicaError(f"{path} has {total} rows, more than one page")


def _parse[M: BaseModel](model: type[M], data: dict, key: str, what: str) -> M:
    try:
        return model.model_validate(data.get(key))
    except ValidationError as exc:
        # The fields at fault, not the values (they're only F1 data, but the
        # rule everywhere is that errors don't echo input).
        fields = sorted({".".join(map(str, e["loc"])) for e in exc.errors()})[:5]
        raise JolpicaError(f"unexpected {what} data: {', '.join(fields)}") from None


def _ordered[S: (DriverStanding, ConstructorStanding)](entries: list[S]) -> list[S]:
    """By position; entries without one (excluded) keep their order, last."""
    ranked = sorted(
        (e for e in entries if e.position is not None),
        key=lambda e: e.position or 0,
    )
    return ranked + [e for e in entries if e.position is None]
