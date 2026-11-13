"""Transform Jolpica's session-based dump tables into ApexGPT's flat F1 schema.

Jolpica stores each weekend as a round with sessions (practice, qualifying,
sprint, race), entries per car (`roundentry` -> `teamdriver`) and results per
session (`sessionentry`). The schema in backend/app/db/models/f1.py is flat and
Ergast-style. The mapping follows the semantics of Jolpica's own Ergast-compatible
API (jolpica_api/ergastapi), so numbers match what that API reports:

- results / sprint_results: entries of the R / SR session. `position` is NULL
  when the car is not classified; `position_order` keeps the full order.
  `time_ms` only for classified cars. Status is the `detail` text, else the
  status enum's name. Fastest lap = the entry's non-deleted fastest lap;
  a fastest-lap rank of 0 ("no timed lap") becomes NULL.
- qualifying: entries of all Q* sessions (QB, QA, QO, Q1-Q3) with a position,
  ordered by session number. Position = the last session's position. Times:
  Q1/Q2/Q3 by session type; other formats fill q1 then q2. Times come from the
  entry's fastest lap.
- standings: championship rows tied to a round (the standings after that race).
  Position is NULL when the entry is ineligible, disqualified or excluded.
- pit_stops: stops during the race session, with the lap number from `lap`.

Only races inside the season range and with race results are loaded (so future
rounds of an in-progress season are skipped). Entities (drivers, constructors,
circuits, seasons) are limited to those the loaded rows reference.
"""

import datetime as dt
import logging
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from structured.dump import Row, TableSource
from structured.errors import DumpError

logger = logging.getLogger(__name__)

FIRST_SEASON = 1950

# Jolpica SessionStatus enum -> status text, used when `detail` is empty.
STATUS_NAMES = {
    0: "Finished",
    1: "Lapped",
    10: "Accident",
    11: "Retired",
    20: "Disqualified",
    30: "Did not start",
    40: "Did not qualify",
    41: "Did not prequalify",
}

# ChampionshipAdjustmentType values above 100 remove the entry from the
# championship (101 = disqualified, 102 = excluded).
_REMOVED_FROM_CHAMPIONSHIP = 100

_DURATION = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?$")
_CENT = Decimal("0.01")

Record = dict[str, Any]


@dataclass
class F1Data:
    """Rows for each table, keyed by our column names, in load order."""

    seasons: list[Record] = field(default_factory=list)
    circuits: list[Record] = field(default_factory=list)
    drivers: list[Record] = field(default_factory=list)
    constructors: list[Record] = field(default_factory=list)
    statuses: list[str] = field(default_factory=list)
    races: list[Record] = field(default_factory=list)
    # results / sprint_results carry `status` (text); the loader maps it to status_id.
    results: list[Record] = field(default_factory=list)
    sprint_results: list[Record] = field(default_factory=list)
    qualifying: list[Record] = field(default_factory=list)
    driver_standings: list[Record] = field(default_factory=list)
    constructor_standings: list[Record] = field(default_factory=list)
    pit_stops: list[Record] = field(default_factory=list)
    skipped_races: int = 0

    def counts(self) -> dict[str, int]:
        return {
            "seasons": len(self.seasons),
            "circuits": len(self.circuits),
            "drivers": len(self.drivers),
            "constructors": len(self.constructors),
            "status": len(self.statuses),
            "races": len(self.races),
            "results": len(self.results),
            "sprint_results": len(self.sprint_results),
            "qualifying": len(self.qualifying),
            "driver_standings": len(self.driver_standings),
            "constructor_standings": len(self.constructor_standings),
            "pit_stops": len(self.pit_stops),
        }


# --- field parsers (raise DumpError with the table and row id) ---


class _Ctx:
    """Names the table/row in error messages."""

    def __init__(self, table: str, row: Row) -> None:
        self.table = table
        self.row = row

    def fail(self, column: str, problem: str) -> DumpError:
        return DumpError(
            f"{self.table} row id={self.row.get('id', '?')}: column {column!r} {problem}"
            f" (value {self.row.get(column)!r})"
        )

    def text(self, column: str) -> str:
        value = (self.row.get(column) or "").strip()
        if not value:
            raise self.fail(column, "is required")
        return value

    def opt_text(self, column: str) -> str | None:
        return (self.row.get(column) or "").strip() or None

    def _number(self, column: str, convert: Callable[[str], Any]) -> Any:
        value = self.opt_text(column)
        if value is None:
            return None
        try:
            return convert(value)
        except (ValueError, InvalidOperation):
            raise self.fail(column, "is not a valid number") from None

    def integer(self, column: str) -> int:
        value = self.opt_int(column)
        if value is None:
            raise self.fail(column, "is required")
        return value

    def opt_int(self, column: str) -> int | None:
        return self._number(column, int)

    def opt_float(self, column: str) -> float | None:
        return self._number(column, float)

    def boolean(self, column: str) -> bool:
        value = self.opt_text(column)
        if value not in ("t", "f"):
            raise self.fail(column, "is not a boolean (t/f)")
        return value == "t"

    def points(self, column: str) -> Decimal:
        value = self._number(column, Decimal)
        if value is None:
            raise self.fail(column, "is required")
        rounded = value.quantize(_CENT)
        # Float artefacts like 1.1400000000000001 round away; real precision loss fails.
        if abs(rounded - value) > Decimal("0.000001"):
            raise self.fail(column, "has more than 2 decimal places")
        return rounded

    def iso_date(self, column: str) -> dt.date:
        try:
            return dt.date.fromisoformat(self.text(column))
        except ValueError:
            raise self.fail(column, "is not an ISO date") from None

    def opt_date(self, column: str) -> dt.date | None:
        return self.iso_date(column) if self.opt_text(column) else None

    def opt_time_of_day(self, column: str) -> dt.time | None:
        value = self.opt_text(column)
        if value is None:
            return None
        try:
            return dt.time.fromisoformat(value)
        except ValueError:
            raise self.fail(column, "is not a time of day") from None

    def opt_ms(self, column: str) -> int | None:
        value = self.opt_text(column)
        if value is None:
            return None
        ms = duration_ms(value)
        if ms is None:
            raise self.fail(column, "is not a duration (HH:MM:SS.fff)")
        return ms


def duration_ms(value: str) -> int | None:
    """'02:13:23.6' -> 8003600. Returns None if the format is not recognised."""
    match = _DURATION.match(value.strip())
    if not match:
        return None
    hours, minutes, seconds, fraction = match.groups()
    if int(minutes) >= 60 or int(seconds) >= 60:
        return None
    micros = int((fraction or "0").ljust(6, "0"))
    millis = (micros + 500) // 1000  # round half up
    return ((int(hours) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + millis


# --- transform ---


@dataclass(frozen=True)
class _Entry:
    """A car's entry in a round: who drove it, for which team, with which number."""

    race_id: int
    driver_id: int
    constructor_id: int
    number: int | None


@dataclass(frozen=True)
class _Session:
    race_id: int
    type: str
    number: int


def transform(
    source: TableSource, first_season: int = FIRST_SEASON, last_season: int = 2025
) -> F1Data:
    if not FIRST_SEASON <= first_season <= last_season <= 2100:
        raise ValueError(
            f"season range must satisfy {FIRST_SEASON} <= first <= last <= 2100"
        )

    years = _season_years(source)
    rounds = _rounds_in_range(source, years, first_season, last_season)
    sessions = _sessions(source, rounds)
    entries = _entries(source, rounds)

    # Session entries by kind. Kept as raw rows until laps are known.
    race_rows: list[Row] = []
    sprint_rows: list[Row] = []
    quali_rows: list[Row] = []
    entry_of_session_entry: dict[int, _Entry] = {}
    for row in source.rows("sessionentry"):
        ctx = _Ctx("sessionentry", row)
        session = sessions.get(ctx.integer("session_id"))
        if session is None:
            continue
        entry = entries.get(ctx.integer("round_entry_id"))
        if entry is None:
            raise ctx.fail("round_entry_id", "references an unknown round entry")
        if session.type == "R":
            race_rows.append(row)
        elif session.type == "SR":
            sprint_rows.append(row)
        elif session.type.startswith("Q") and ctx.opt_int("position") is not None:
            quali_rows.append(row)
        else:
            continue
        entry_of_session_entry[ctx.integer("id")] = entry

    race_session_entries = {_Ctx("sessionentry", r).integer("id") for r in race_rows}
    pit_rows = [
        row
        for row in source.rows("pitstop")
        if _Ctx("pitstop", row).integer("session_entry_id") in race_session_entries
    ]
    lap_ids_needed = {_Ctx("pitstop", row).integer("lap_id") for row in pit_rows}
    fastest_laps, lap_numbers = _laps(
        source, set(entry_of_session_entry), lap_ids_needed
    )

    data = F1Data()
    data.results = [
        _result(row, entry_of_session_entry, fastest_laps, with_rank=True)
        for row in race_rows
    ]
    data.sprint_results = [
        _result(row, entry_of_session_entry, fastest_laps, with_rank=False)
        for row in sprint_rows
    ]

    # Only races that have results (skips future rounds of an in-progress season).
    raced = {r["race_id"] for r in data.results}
    data.skipped_races = len(rounds) - len(raced)
    data.sprint_results = [r for r in data.sprint_results if r["race_id"] in raced]
    data.qualifying = _qualifying(
        quali_rows, sessions, entry_of_session_entry, fastest_laps
    )
    data.qualifying = [r for r in data.qualifying if r["race_id"] in raced]
    data.pit_stops = _pit_stops(pit_rows, entry_of_session_entry, lap_numbers)
    data.driver_standings = _standings(
        source, "driverchampionship", "driver_id", "driver_id", raced
    )
    data.constructor_standings = _standings(
        source, "teamchampionship", "team_id", "constructor_id", raced
    )
    _check_unique(data.sprint_results, ("race_id", "driver_id"), "sprint_results")
    _check_unique(data.pit_stops, ("race_id", "driver_id", "stop"), "pit_stops")
    _check_unique(data.driver_standings, ("race_id", "driver_id"), "driver_standings")
    _check_unique(
        data.constructor_standings,
        ("race_id", "constructor_id"),
        "constructor_standings",
    )

    data.statuses = sorted({r["status"] for r in data.results + data.sprint_results})

    # Entities referenced by the loaded rows.
    race_rows_out = [r for race_id, r in sorted(rounds.items()) if race_id in raced]
    data.races = race_rows_out
    fact_rows = (
        data.results
        + data.sprint_results
        + data.qualifying
        + data.driver_standings
        + data.pit_stops
    )
    driver_ids = {r["driver_id"] for r in fact_rows}
    constructor_ids = {
        r["constructor_id"]
        for r in data.results
        + data.sprint_results
        + data.qualifying
        + data.constructor_standings
    }
    data.drivers = _drivers(source, driver_ids)
    data.constructors = _constructors(source, constructor_ids)
    data.circuits = _circuits(source, {r["circuit_id"] for r in data.races})
    season_years = {r["season"] for r in data.races}
    data.seasons = [
        {"year": year, "wikipedia_url": url}
        for year, url in sorted(years.values())
        if year in season_years
    ]
    logger.info(
        "Transformed seasons %s-%s: %s", first_season, last_season, data.counts()
    )
    return data


def _season_years(source: TableSource) -> dict[int, tuple[int, str | None]]:
    """season id -> (year, wikipedia url)."""
    years = {}
    for row in source.rows("season"):
        ctx = _Ctx("season", row)
        years[ctx.integer("id")] = (ctx.integer("year"), ctx.opt_text("wikipedia"))
    return years


def _rounds_in_range(
    source: TableSource,
    years: dict[int, tuple[int, str | None]],
    first: int,
    last: int,
) -> dict[int, Record]:
    """race_id (round id) -> races row, for non-cancelled rounds in range."""
    races = {}
    for row in source.rows("round"):
        ctx = _Ctx("round", row)
        season_id = ctx.integer("season_id")
        if season_id not in years:
            raise ctx.fail("season_id", "references an unknown season")
        year = years[season_id][0]
        if not first <= year <= last or ctx.boolean("is_cancelled"):
            continue
        race_id = ctx.integer("id")
        races[race_id] = {
            "race_id": race_id,
            "season": year,
            "round": ctx.integer("number"),
            "name": ctx.text("name"),
            "circuit_id": ctx.integer("circuit_id"),
            "date": ctx.iso_date("date"),
            "wikipedia_url": ctx.opt_text("wikipedia"),
        }
    _check_unique(list(races.values()), ("season", "round"), "races")
    return races


def _sessions(source: TableSource, rounds: dict[int, Record]) -> dict[int, _Session]:
    sessions = {}
    for row in source.rows("session"):
        ctx = _Ctx("session", row)
        race_id = ctx.integer("round_id")
        if race_id not in rounds or ctx.boolean("is_cancelled"):
            continue
        sessions[ctx.integer("id")] = _Session(
            race_id=race_id, type=ctx.text("type"), number=ctx.opt_int("number") or 0
        )
    return sessions


def _entries(source: TableSource, rounds: dict[int, Record]) -> dict[int, _Entry]:
    team_drivers = {}
    for row in source.rows("teamdriver"):
        ctx = _Ctx("teamdriver", row)
        team_drivers[ctx.integer("id")] = (
            ctx.integer("driver_id"),
            ctx.integer("team_id"),
        )

    entries = {}
    for row in source.rows("roundentry"):
        ctx = _Ctx("roundentry", row)
        race_id = ctx.integer("round_id")
        if race_id not in rounds:
            continue
        team_driver = team_drivers.get(ctx.integer("team_driver_id"))
        if team_driver is None:
            raise ctx.fail("team_driver_id", "references an unknown team driver")
        entries[ctx.integer("id")] = _Entry(
            race_id=race_id,
            driver_id=team_driver[0],
            constructor_id=team_driver[1],
            number=ctx.opt_int("car_number"),
        )
    return entries


def _laps(
    source: TableSource, session_entries: set[int], lap_ids: set[int]
) -> tuple[dict[int, tuple[int | None, int]], dict[int, int]]:
    """One pass over the (large) lap table.

    Returns (session entry id -> (fastest lap number, fastest lap ms), lap id -> lap number).
    """
    fastest: dict[int, tuple[int | None, int]] = {}
    numbers: dict[int, int] = {}
    for row in source.rows("lap"):
        ctx = _Ctx("lap", row)
        lap_id = ctx.integer("id")
        if lap_id in lap_ids:
            numbers[lap_id] = ctx.integer("number")
        if not ctx.boolean("is_entry_fastest_lap") or ctx.boolean("is_deleted"):
            continue
        entry_id = ctx.integer("session_entry_id")
        if entry_id not in session_entries:
            continue
        ms = ctx.opt_ms("time")
        if ms is None or ms <= 0:
            continue
        if entry_id not in fastest or ms < fastest[entry_id][1]:
            fastest[entry_id] = (ctx.opt_int("number"), ms)
    missing = lap_ids - numbers.keys()
    if missing:
        raise DumpError(
            f"pit stops reference {len(missing)} unknown laps (e.g. id={min(missing)})"
        )
    return fastest, numbers


def _status_text(ctx: _Ctx) -> str:
    detail = ctx.opt_text("detail")
    if detail:
        return detail
    code = ctx.opt_int("status")
    if code not in STATUS_NAMES:
        raise ctx.fail("status", "is an unknown status code and detail is empty")
    return STATUS_NAMES[code]


def _result(
    row: Row,
    entry_of: dict[int, _Entry],
    fastest_laps: dict[int, tuple[int | None, int]],
    *,
    with_rank: bool,
) -> Record:
    ctx = _Ctx("sessionentry", row)
    entry_id = ctx.integer("id")
    entry = entry_of[entry_id]
    classified = ctx.boolean("is_classified")
    position = ctx.integer("position")
    fastest_number, fastest_ms = fastest_laps.get(entry_id, (None, None))
    record: Record = {
        "result_id" if with_rank else "sprint_result_id": entry_id,
        "race_id": entry.race_id,
        "driver_id": entry.driver_id,
        "constructor_id": entry.constructor_id,
        "number": entry.number,
        "grid": ctx.integer("grid"),
        "position": position if classified else None,
        "position_order": position,
        "points": ctx.points("points"),
        "laps": ctx.integer("laps_completed"),
        "time_ms": ctx.opt_ms("time") if classified else None,
        "fastest_lap_number": fastest_number,
        "fastest_lap_ms": fastest_ms,
        "status": _status_text(ctx),
    }
    if with_rank:
        # Jolpica uses rank 0 for "no timed lap" (mostly cars out on lap 1).
        record["fastest_lap_rank"] = ctx.opt_int("fastest_lap_rank") or None
    return record


def _qualifying(
    rows: list[Row],
    sessions: dict[int, _Session],
    entry_of: dict[int, _Entry],
    fastest_laps: dict[int, tuple[int | None, int]],
) -> list[Record]:
    by_entry: dict[_Entry, list[tuple[_Session, int, int | None]]] = defaultdict(list)
    for row in rows:
        ctx = _Ctx("sessionentry", row)
        entry_id = ctx.integer("id")
        session = sessions[ctx.integer("session_id")]
        lap = fastest_laps.get(entry_id)
        quali_ms = lap[1] if lap else ctx.opt_ms("time")
        by_entry[entry_of[entry_id]].append(
            (session, ctx.integer("position"), quali_ms)
        )

    best: dict[tuple[int, int], Record] = {}
    for entry, results in by_entry.items():
        results.sort(key=lambda r: r[0].number)
        times: dict[str, int | None] = {"q1_ms": None, "q2_ms": None, "q3_ms": None}
        for session, _, ms in results:
            if session.type in ("Q1", "Q2", "Q3"):
                times[f"{session.type.lower()}_ms"] = ms
            elif times["q1_ms"] is None:
                times["q1_ms"] = ms
            else:
                times["q2_ms"] = ms
        record = {
            "race_id": entry.race_id,
            "driver_id": entry.driver_id,
            "constructor_id": entry.constructor_id,
            "number": entry.number,
            "position": results[-1][1],
            **times,
        }
        # One row per driver per race; a driver entered in two cars (1950s)
        # keeps their better-qualified car.
        key = (entry.race_id, entry.driver_id)
        if key not in best or record["position"] < best[key]["position"]:
            best[key] = record
    return sorted(best.values(), key=lambda r: (r["race_id"], r["position"]))


def _pit_stops(
    rows: list[Row], entry_of: dict[int, _Entry], lap_numbers: dict[int, int]
) -> list[Record]:
    stops = []
    for row in rows:
        ctx = _Ctx("pitstop", row)
        entry = entry_of[ctx.integer("session_entry_id")]
        duration = ctx.opt_ms("duration")
        if duration is None:
            raise ctx.fail("duration", "is required")
        stops.append(
            {
                "race_id": entry.race_id,
                "driver_id": entry.driver_id,
                "stop": ctx.integer("number"),
                "lap": lap_numbers[ctx.integer("lap_id")],
                "local_time": ctx.opt_time_of_day("local_timestamp"),
                "duration_ms": duration,
            }
        )
    return stops


def _standings(
    source: TableSource, table: str, source_key: str, key: str, races: set[int]
) -> list[Record]:
    rows = []
    for row in source.rows(table):
        ctx = _Ctx(table, row)
        race_id = ctx.opt_int("round_id")
        if race_id is None or race_id not in races:
            continue
        removed = (ctx.opt_int("adjustment_type") or 0) > _REMOVED_FROM_CHAMPIONSHIP
        eligible = ctx.boolean("is_eligible") and not removed
        rows.append(
            {
                "race_id": race_id,
                key: ctx.integer(source_key),
                "points": ctx.points("points"),
                "position": ctx.opt_int("position") if eligible else None,
                "wins": ctx.integer("win_count"),
            }
        )
    return rows


def _drivers(source: TableSource, ids: set[int]) -> list[Record]:
    drivers = []
    for row in source.rows("driver"):
        ctx = _Ctx("driver", row)
        driver_id = ctx.integer("id")
        if driver_id not in ids:
            continue
        code = ctx.opt_text("abbreviation")
        if code is not None and len(code) != 3:
            raise ctx.fail("abbreviation", "must be 3 characters")
        drivers.append(
            {
                "driver_id": driver_id,
                "ref": ctx.text("reference"),
                "code": code,
                "number": ctx.opt_int("permanent_car_number"),
                "forename": ctx.text("forename"),
                "surname": ctx.text("surname"),
                "date_of_birth": ctx.opt_date("date_of_birth"),
                "nationality": ctx.opt_text("nationality"),
                "wikipedia_url": ctx.opt_text("wikipedia"),
            }
        )
    _check_all_found(ids, {d["driver_id"] for d in drivers}, "driver")
    return drivers


def _constructors(source: TableSource, ids: set[int]) -> list[Record]:
    constructors = []
    for row in source.rows("team"):
        ctx = _Ctx("team", row)
        team_id = ctx.integer("id")
        if team_id not in ids:
            continue
        constructors.append(
            {
                "constructor_id": team_id,
                "ref": ctx.text("reference"),
                "name": ctx.text("name"),
                "nationality": ctx.opt_text("nationality"),
                "wikipedia_url": ctx.opt_text("wikipedia"),
            }
        )
    _check_all_found(ids, {c["constructor_id"] for c in constructors}, "team")
    return constructors


def _circuits(source: TableSource, ids: set[int]) -> list[Record]:
    circuits = []
    for row in source.rows("circuit"):
        ctx = _Ctx("circuit", row)
        circuit_id = ctx.integer("id")
        if circuit_id not in ids:
            continue
        circuits.append(
            {
                "circuit_id": circuit_id,
                "ref": ctx.text("reference"),
                "name": ctx.text("name"),
                "locality": ctx.opt_text("locality"),
                "country": ctx.opt_text("country"),
                "lat": ctx.opt_float("latitude"),
                "lng": ctx.opt_float("longitude"),
                "altitude": ctx.opt_int("altitude"),
                "wikipedia_url": ctx.opt_text("wikipedia"),
            }
        )
    _check_all_found(ids, {c["circuit_id"] for c in circuits}, "circuit")
    return circuits


def _check_all_found(wanted: set[int], found: set[int], table: str) -> None:
    missing = wanted - found
    if missing:
        raise DumpError(
            f"{len(missing)} referenced {table} rows are missing (e.g. id={min(missing)})"
        )


def _check_unique(rows: Iterable[Record], key: tuple[str, ...], table: str) -> None:
    seen: set[tuple[Any, ...]] = set()
    for row in rows:
        value = tuple(row[k] for k in key)
        if value in seen:
            raise DumpError(f"{table}: duplicate {', '.join(key)} = {value}")
        seen.add(value)
