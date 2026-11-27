"""A fake Jolpica API for the season tests (F8.3): MRData documents, served
through httpx.MockTransport, so no test reaches the network."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import httpx


def mrdata(key: str, table: dict, total: int | None = None) -> dict:
    rows = table.get("Races") or table.get("StandingsLists") or []
    return {"MRData": {"limit": "100", "offset": "0",
                       "total": str(len(rows) if total is None else total),
                       key: table}}  # fmt: skip


def race(season: int, rnd: int, date: str, time: str | None = "14:00:00Z",
         **sessions: dict) -> dict:  # fmt: skip
    out = {
        "season": str(season),
        "round": str(rnd),
        "url": f"https://en.wikipedia.org/wiki/{season}_Round_{rnd}",
        "raceName": f"Grand Prix {rnd}",
        "Circuit": {
            "circuitId": f"circuit_{rnd}",
            "circuitName": f"Circuit {rnd}",
            "Location": {"lat": "1", "long": "2", "locality": "Town",
                         "country": "Country"},
        },  # fmt: skip
        "date": date,
        **sessions,
    }
    if time is not None:
        out["time"] = time
    return out


def calendar(season: int, races: list[dict]) -> dict:
    return mrdata("RaceTable", {"season": str(season), "Races": races})


def driver_entry(pos: int | None, given: str, family: str, points: str,
                 wins: str = "0", teams: tuple[str, ...] = ("Team A",)) -> dict:  # fmt: skip
    entry = {
        "positionText": str(pos) if pos else "D",
        "points": points,
        "wins": wins,
        "Driver": {"driverId": family.lower(), "permanentNumber": "44",
                   "code": family[:3].upper(), "givenName": given,
                   "familyName": family, "nationality": "British"},
        "Constructors": [{"constructorId": t.lower().replace(" ", "_"), "name": t,
                          "nationality": "British"} for t in teams],
    }  # fmt: skip
    if pos:
        entry["position"] = str(pos)
    return entry


def constructor_entry(pos: int, name: str, points: str, wins: str = "0") -> dict:
    return {"position": str(pos), "positionText": str(pos), "points": points,
            "wins": wins,
            "Constructor": {"constructorId": name.lower().replace(" ", "_"),
                            "name": name, "nationality": "British"}}  # fmt: skip


def drivers(season: int, rnd: int | None, entries: list[dict]) -> dict:
    lists = [] if rnd is None else [
        {"season": str(season), "round": str(rnd), "DriverStandings": entries}
    ]  # fmt: skip
    return mrdata("StandingsTable", {"season": str(season), "StandingsLists": lists})


def constructors(season: int, rnd: int | None, entries: list[dict]) -> dict:
    lists = [] if rnd is None else [
        {"season": str(season), "round": str(rnd), "ConstructorStandings": entries}
    ]  # fmt: skip
    return mrdata("StandingsTable", {"season": str(season), "StandingsLists": lists})


DRIVERS = [
    driver_entry(2, "Lando", "Norris", "300", "4"),
    driver_entry(1, "Kimi", "Antonelli", "402.5", "9", ("Team B", "Mercedes")),
]
CONSTRUCTORS = [constructor_entry(1, "Mercedes", "666", "12"),
                constructor_entry(2, "McLaren", "500", "5")]  # fmt: skip

Reply = dict | httpx.Response | Exception


@dataclass
class FakeJolpica:
    """Path (e.g. "current/driverStandings.json") → a document, a response or
    an exception to raise. Unknown paths are 404s."""

    routes: dict[str, Reply] = field(default_factory=dict)
    requests: list[httpx.Request] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/ergast/f1/")
        reply = self.routes.get(path)
        if reply is None:
            return httpx.Response(404, json={"detail": "Not found."})
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, httpx.Response):
            return reply
        return httpx.Response(200, content=json.dumps(reply).encode())

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def paths(self) -> list[str]:
        return [r.url.path.removeprefix("/ergast/f1/") for r in self.requests]


def in_season(**overrides: Reply) -> FakeJolpica:
    """2026 after round 2 of 3, the last race on 6 December."""
    routes: dict[str, Reply] = {
        "current.json": calendar(2026, [
            race(2026, 1, "2026-03-08"),
            race(2026, 3, "2026-12-06", "13:00:00Z",
                 Qualifying={"date": "2026-12-05", "time": "14:00:00Z"},
                 Sprint={"date": "2026-12-05", "time": "10:00:00Z"},
                 FirstPractice={"date": "2026-12-04", "time": "09:30:00Z"},
                 SprintQualifying={"date": "2026-12-04", "time": "13:30:00Z"}),
            race(2026, 2, "2026-11-29", "16:00:00Z"),
        ]),
        "current/driverStandings.json": drivers(2026, 2, DRIVERS),
        "current/constructorStandings.json": constructors(2026, 2, CONSTRUCTORS),
    }  # fmt: skip
    routes.update(overrides)
    return FakeJolpica(routes)
