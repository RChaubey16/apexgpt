"""The current season's standings and next race, cached (F8.3).

    snapshot = await service.current()   # SeasonSnapshot, or SeasonUnavailable

One refresh makes 3 Jolpica requests (4 in the off-season), at most once per
SEASON_CACHE_TTL_SECONDS (default 600, Jolpica's own cache time). Jolpica
allows 500 requests an hour, so the cache keeps us far below it whatever the
traffic. Concurrent requests share one refresh (a lock).

When a refresh fails, the last good snapshot is served with `stale: true` for
up to STALE_MAX_SECONDS, and Jolpica is asked again after RETRY_SECONDS, not
on every request. With nothing usable cached, SeasonUnavailable (the route's
503).

Which season, and the off-season:

- The standings are the latest season with results. Between seasons, after
  Jolpica's "current" moves to a year with no races yet, that's the year
  before, marked complete.
- `complete` is true once the standings include the calendar's last round.
- The next race is the first race not finished yet (its start + RACE_HOURS),
  so a race stays "next" while it runs. After the finale it's the next
  season's opener once that calendar is published, None until then.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
from collections.abc import Callable

import httpx
from pydantic import BaseModel, Field

from app import __version__
from app.season.jolpica import (
    Calendar,
    ConstructorStanding,
    DriverStanding,
    JolpicaClient,
    JolpicaError,
    Race,
    SessionKind,
)

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10.0
STALE_MAX_SECONDS = 86_400
RETRY_SECONDS = 60
# A race (with its formation lap and a red flag or two) is over by then.
RACE_HOURS = 3
USER_AGENT = f"apexgpt-backend/{__version__}"


class SeasonUnavailable(Exception):
    """No current-season data could be fetched, and none is cached."""


# --- the response -----------------------------------------------------------------


class DriverRow(BaseModel):
    position: int | None = Field(description="None if excluded from the standings")
    position_text: str
    driver_id: str
    code: str | None
    number: int | None
    given_name: str
    family_name: str
    nationality: str | None
    team: str | None = Field(description="The latest team this season")
    team_id: str | None
    points: float
    wins: int


class ConstructorRow(BaseModel):
    position: int | None
    position_text: str
    constructor_id: str
    name: str
    nationality: str | None
    points: float
    wins: int


class CircuitInfo(BaseModel):
    circuit_id: str
    name: str
    locality: str
    country: str


class Session(BaseModel):
    kind: SessionKind
    date: dt.date
    start: dt.datetime | None = Field(
        description="UTC; None while the time isn't published"
    )


class NextRace(BaseModel):
    season: int
    round: int
    name: str
    url: str | None
    circuit: CircuitInfo
    date: dt.date
    start: dt.datetime | None
    sessions: list[Session] = Field(description="In order, the race last")


class SeasonSnapshot(BaseModel):
    season: int = Field(description="The season the standings are for")
    round: int | None = Field(description="Standings after this round")
    total_rounds: int | None = Field(description="Rounds in the season's calendar")
    complete: bool = Field(description="The standings are final")
    drivers: list[DriverRow]
    constructors: list[ConstructorRow]
    next_race: NextRace | None
    fetched_at: dt.datetime
    stale: bool = Field(
        default=False, description="Jolpica is unreachable; this is the last data"
    )


# --- building it ----------------------------------------------------------------------


def _driver_row(entry: DriverStanding) -> DriverRow:
    team = entry.constructors[-1] if entry.constructors else None
    d = entry.driver
    return DriverRow(
        position=entry.position, position_text=entry.position_text,
        driver_id=d.driver_id, code=d.code, number=d.number,
        given_name=d.given_name, family_name=d.family_name,
        nationality=d.nationality,
        team=team.name if team else None,
        team_id=team.constructor_id if team else None,
        points=entry.points, wins=entry.wins,
    )  # fmt: skip


def _constructor_row(entry: ConstructorStanding) -> ConstructorRow:
    c = entry.constructor
    return ConstructorRow(
        position=entry.position, position_text=entry.position_text,
        constructor_id=c.constructor_id, name=c.name, nationality=c.nationality,
        points=entry.points, wins=entry.wins,
    )  # fmt: skip


def _finished(race: Race, now: dt.datetime) -> bool:
    start = race.schedule.start
    if start is None:  # no time yet: over once its day (UTC) is
        start = dt.datetime.combine(race.date, dt.time.max, tzinfo=dt.UTC)
        return now > start
    return now >= start + dt.timedelta(hours=RACE_HOURS)


def next_race(calendar: Calendar | None, now: dt.datetime) -> Race | None:
    if calendar is None:
        return None
    return next((race for race in calendar.races if not _finished(race, now)), None)


def _next_race_info(race: Race) -> NextRace:
    c = race.circuit
    return NextRace(
        season=race.season,
        round=race.round,
        name=race.name,
        url=race.url,
        circuit=CircuitInfo(
            circuit_id=c.circuit_id,
            name=c.name,
            locality=c.location.locality,
            country=c.location.country,
        ),
        date=race.date,
        start=race.schedule.start,
        sessions=[
            Session(kind=kind, date=when.date, start=when.start)
            for kind, when in race.sessions()
        ],
    )


async def build_snapshot(client: JolpicaClient, now: dt.datetime) -> SeasonSnapshot:
    """Raises JolpicaError."""
    calendar, drivers, constructors = await asyncio.gather(
        client.calendar("current"),
        client.driver_standings("current"),
        client.constructor_standings("current"),
    )
    if calendar is None:
        raise JolpicaError("no current calendar")
    if drivers.season != calendar.season or constructors.season != drivers.season:
        raise JolpicaError("the calendar and standings are for different seasons")
    if drivers.round != constructors.round:
        # Jolpica updates the two a moment apart; the next refresh agrees.
        raise JolpicaError("driver and constructor standings are rounds apart")

    upcoming = next_race(calendar, now)
    total_rounds: int | None = len(calendar.races)
    if drivers.round is None:
        # A new season with no races yet: the previous season's final standings.
        previous = str(calendar.season - 1)
        drivers, constructors = await asyncio.gather(
            client.driver_standings(previous), client.constructor_standings(previous)
        )
        if drivers.round != constructors.round:
            raise JolpicaError("driver and constructor standings are rounds apart")
        total_rounds = drivers.round
        complete = True
    else:
        complete = drivers.round >= len(calendar.races)
        if upcoming is None:
            upcoming = next_race(await client.calendar(str(calendar.season + 1)), now)

    return SeasonSnapshot(
        season=drivers.season,
        round=drivers.round,
        total_rounds=total_rounds,
        complete=complete,
        drivers=[_driver_row(e) for e in drivers.entries],
        constructors=[_constructor_row(e) for e in constructors.entries],
        next_race=_next_race_info(upcoming) if upcoming else None,
        fetched_at=now,
    )


# --- the cache ---------------------------------------------------------------------------


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class SeasonService:
    def __init__(
        self,
        base_url: str,
        ttl_seconds: int,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        now: Callable[[], dt.datetime] = utc_now,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._base_url = base_url.rstrip("/") + "/"
        self._ttl = ttl_seconds
        self._transport = transport  # tests pass httpx.MockTransport
        self._now, self._clock = now, clock
        self._lock = asyncio.Lock()
        self._snapshot: SeasonSnapshot | None = None
        self._fetched = 0.0  # clock() of the snapshot
        self._failed: float | None = None  # clock() of the last failed refresh

    async def current(self) -> SeasonSnapshot:
        cached = self._usable()
        if cached is not None:
            return cached
        async with self._lock:
            cached = self._usable()  # another request may have just refreshed
            if cached is not None:
                return cached
            return await self._refresh()

    def _usable(self) -> SeasonSnapshot | None:
        """A fresh snapshot, or a stale one while waiting to retry."""
        if self._snapshot is None:
            return None
        age = self._clock() - self._fetched
        if age < self._ttl:
            return self._snapshot
        waiting = (
            self._failed is not None and self._clock() - self._failed < RETRY_SECONDS
        )
        if waiting and age <= STALE_MAX_SECONDS:
            return self._snapshot.model_copy(update={"stale": True})
        return None

    async def _refresh(self) -> SeasonSnapshot:
        # Nothing usable is cached (`_usable` said so): after a failure, don't
        # ask Jolpica again on every request.
        if self._failed is not None and self._clock() - self._failed < RETRY_SECONDS:
            raise SeasonUnavailable
        started = self._clock()
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=TIMEOUT_SECONDS,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                transport=self._transport,
                follow_redirects=False,
            ) as http:
                snapshot = await build_snapshot(JolpicaClient(http), self._now())
        except JolpicaError as exc:
            self._failed = self._clock()
            age = None if self._snapshot is None else round(started - self._fetched)
            logger.warning(
                "Season refresh failed: %s",
                exc,
                extra={"event": "season_refresh", "outcome": "error",
                       "error": str(exc), "stale_age_seconds": age},
            )  # fmt: skip
            if (
                self._snapshot is not None
                and age is not None
                and age <= STALE_MAX_SECONDS
            ):
                return self._snapshot.model_copy(update={"stale": True})
            raise SeasonUnavailable from None
        self._snapshot, self._fetched, self._failed = snapshot, self._clock(), None
        logger.info(
            "Season refreshed",
            extra={"event": "season_refresh", "outcome": "ok",
                   "season": snapshot.season, "round": snapshot.round,
                   "ms": round((self._clock() - started) * 1000)},
        )  # fmt: skip
        return snapshot
