"""The current season snapshot and its cache (F8.3), against a fake Jolpica."""

import asyncio
import datetime as dt
import logging

import httpx
import pytest

from app.season.jolpica import JolpicaClient, JolpicaError
from app.season.service import (
    RETRY_SECONDS,
    STALE_MAX_SECONDS,
    SeasonService,
    SeasonUnavailable,
    build_snapshot,
)
from tests.season.fakes import (
    CONSTRUCTORS,
    DRIVERS,
    FakeJolpica,
    calendar,
    constructor_entry,
    constructors,
    driver_entry,
    drivers,
    in_season,
    mrdata,
    race,
)

BASE = "https://api.jolpi.ca/ergast/f1"
NOW = dt.datetime(2026, 11, 27, 9, 0, tzinfo=dt.UTC)


def snapshot(fake: FakeJolpica, now: dt.datetime = NOW):
    async def run():
        async with httpx.AsyncClient(
            base_url=BASE + "/", transport=fake.transport
        ) as http:
            return await build_snapshot(JolpicaClient(http), now)

    return asyncio.run(run())


# --- the snapshot ------------------------------------------------------------------


def test_in_season_snapshot() -> None:
    snap = snapshot(in_season())
    assert (snap.season, snap.round, snap.total_rounds, snap.complete) == (
        2026, 2, 3, False,
    )  # fmt: skip
    assert [d.family_name for d in snap.drivers] == ["Antonelli", "Norris"]
    leader = snap.drivers[0]
    assert leader.points == 402.5 and leader.wins == 9 and leader.code == "ANT"
    assert (leader.team, leader.team_id) == ("Mercedes", "mercedes")  # latest team
    assert [c.name for c in snap.constructors] == ["Mercedes", "McLaren"]
    assert snap.next_race is not None and snap.next_race.round == 2
    assert snap.next_race.start == dt.datetime(2026, 11, 29, 16, tzinfo=dt.UTC)
    assert snap.fetched_at == NOW and snap.stale is False


def test_requests_ask_for_a_whole_season() -> None:
    fake = in_season()
    snapshot(fake)
    assert sorted(fake.paths()) == [
        "current.json", "current/constructorStandings.json",
        "current/driverStandings.json",
    ]  # fmt: skip
    assert all(r.url.params["limit"] == "100" for r in fake.requests)


def test_sessions_are_in_order_with_the_race_last() -> None:
    later = NOW.replace(month=12, day=1)
    snap = snapshot(in_season(), later)
    assert snap.next_race is not None and snap.next_race.round == 3
    assert [(s.kind, s.start.isoformat()) for s in snap.next_race.sessions] == [
        ("practice_1", "2026-12-04T09:30:00+00:00"),
        ("sprint_qualifying", "2026-12-04T13:30:00+00:00"),
        ("sprint", "2026-12-05T10:00:00+00:00"),
        ("qualifying", "2026-12-05T14:00:00+00:00"),
        ("race", "2026-12-06T13:00:00+00:00"),
    ]


def test_a_race_stays_next_while_it_runs() -> None:
    during = dt.datetime(2026, 11, 29, 18, 30, tzinfo=dt.UTC)  # started 16:00
    assert snapshot(in_season(), during).next_race.round == 2
    after = dt.datetime(2026, 11, 29, 19, 0, tzinfo=dt.UTC)
    assert snapshot(in_season(), after).next_race.round == 3


def test_a_race_without_a_time_is_next_until_its_day_ends() -> None:
    fake = in_season(**{"current.json": calendar(2026, [
        race(2026, 1, "2026-03-08"), race(2026, 2, "2026-11-29", None),
        race(2026, 3, "2026-12-06"),
    ])})  # fmt: skip
    late = dt.datetime(2026, 11, 29, 23, 0, tzinfo=dt.UTC)
    snap = snapshot(fake, late)
    assert snap.next_race.round == 2 and snap.next_race.start is None
    assert snap.next_race.sessions[-1].start is None
    assert snapshot(fake, late + dt.timedelta(hours=2)).next_race.round == 3


def test_after_the_finale_the_next_opener_once_published() -> None:
    fake = in_season(**{
        "current/driverStandings.json": drivers(2026, 3, DRIVERS),
        "current/constructorStandings.json": constructors(2026, 3, CONSTRUCTORS),
        "2027.json": calendar(2027, [race(2027, 2, "2027-03-21"),
                                     race(2027, 1, "2027-03-07")]),
    })  # fmt: skip
    snap = snapshot(fake, dt.datetime(2026, 12, 10, tzinfo=dt.UTC))
    assert snap.complete is True and snap.season == 2026 and snap.round == 3
    assert (snap.next_race.season, snap.next_race.round) == (2027, 1)


def test_after_the_finale_no_next_race_until_the_calendar_is_out() -> None:
    fake = in_season(
        **{
            "current/driverStandings.json": drivers(2026, 3, DRIVERS),
            "current/constructorStandings.json": constructors(2026, 3, CONSTRUCTORS),
        }
    )  # fmt: skip  (2027.json → 404)
    snap = snapshot(fake, dt.datetime(2026, 12, 10, tzinfo=dt.UTC))
    assert snap.complete is True and snap.next_race is None
    assert "2027.json" in fake.paths()


def test_an_empty_next_calendar_is_no_next_race() -> None:
    fake = in_season(**{
        "current/driverStandings.json": drivers(2026, 3, DRIVERS),
        "current/constructorStandings.json": constructors(2026, 3, CONSTRUCTORS),
        "2027.json": calendar(2027, []),
    })  # fmt: skip
    assert snapshot(fake, dt.datetime(2026, 12, 10, tzinfo=dt.UTC)).next_race is None


def test_a_new_season_before_its_first_race_shows_last_seasons_final() -> None:
    fake = FakeJolpica({
        "current.json": calendar(2027, [race(2027, 1, "2027-03-07")]),
        "current/driverStandings.json": drivers(2027, None, []),
        "current/constructorStandings.json": constructors(2027, None, []),
        "2026/driverStandings.json": drivers(2026, 24, DRIVERS),
        "2026/constructorStandings.json": constructors(2026, 24, CONSTRUCTORS),
    })  # fmt: skip
    snap = snapshot(fake, dt.datetime(2027, 1, 15, tzinfo=dt.UTC))
    assert (snap.season, snap.round, snap.total_rounds, snap.complete) == (
        2026, 24, 24, True,
    )  # fmt: skip
    assert len(snap.drivers) == 2
    assert (snap.next_race.season, snap.next_race.round) == (2027, 1)


def test_an_excluded_driver_comes_last_without_a_position() -> None:
    fake = in_season(**{"current/driverStandings.json": drivers(
        2026, 2, [driver_entry(None, "Michael", "Schumacher", "78"), *DRIVERS]
    )})  # fmt: skip
    rows = snapshot(fake).drivers
    assert [r.family_name for r in rows][-1] == "Schumacher"
    assert rows[-1].position is None and rows[-1].position_text == "D"


# --- bad upstream data -------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"current.json": {"oops": 1}}, "no MRData"),
        ({"current.json": httpx.Response(200, content=b"<html>")}, "not JSON"),
        ({"current.json": httpx.Response(429)}, "HTTP 429"),
        ({"current.json": httpx.Response(500)}, "HTTP 500"),
        ({"current.json": httpx.ConnectError("refused")}, "ConnectError"),
        ({"current.json": httpx.ReadTimeout("slow")}, "timed out"),
        ({"current/driverStandings.json": httpx.Response(404)}, "HTTP 404"),
        ({"current.json": calendar(2026, [])}, "no current calendar"),
        ({"current/driverStandings.json": drivers(
            2026, 2, [{**DRIVERS[0], "points": "lots"}])}, "unexpected"),
        ({"current/driverStandings.json": drivers(2026, 1, DRIVERS)},
         "rounds apart"),
        ({"current/driverStandings.json": drivers(2025, 2, DRIVERS)},
         "different seasons"),
        ({"current.json": mrdata("RaceTable", {"season": "2026", "Races": [
            race(2026, 1, "2026-03-08")]}, total=101)}, "more than one page"),
        ({"current.json": calendar(2026, [race(2026, 1, "2026-03-08"),
                                          race(2026, 1, "2026-03-15")])},
         "repeated rounds"),
        ({"current.json": calendar(2026, [race(2026, 1, "2026-12-06",
                                               Sprint={"date": "soon"})])},
         "bad Sprint time"),
        ({"current.json": httpx.Response(200, content=b" " * 2_000_001)},
         "too large"),
    ],
)  # fmt: skip
def test_bad_upstream_data_is_a_jolpica_error(overrides: dict, message: str) -> None:
    with pytest.raises(JolpicaError, match=message):
        snapshot(in_season(**overrides))


def test_validation_errors_name_fields_not_values() -> None:
    fake = in_season(**{"current/driverStandings.json": drivers(
        2026, 2, [{**DRIVERS[0], "points": "secret-looking-value"}])})  # fmt: skip
    with pytest.raises(JolpicaError) as caught:
        snapshot(fake)
    assert "points" in str(caught.value)
    assert "secret-looking-value" not in str(caught.value)


# --- the cache -----------------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def service(fake: FakeJolpica, clock: Clock, ttl: int = 600) -> SeasonService:
    return SeasonService(BASE, ttl, transport=fake.transport, now=lambda: NOW,
                         clock=clock)  # fmt: skip


def test_the_cache_serves_until_its_ttl() -> None:
    fake, clock = in_season(), Clock()
    svc = service(fake, clock)
    first = asyncio.run(svc.current())
    clock.t += 599
    assert asyncio.run(svc.current()) is first
    assert len(fake.requests) == 3
    clock.t += 1
    asyncio.run(svc.current())
    assert len(fake.requests) == 6


def test_concurrent_requests_share_one_refresh() -> None:
    fake = in_season()
    svc = service(fake, Clock())

    async def many():
        return await asyncio.gather(*(svc.current() for _ in range(10)))

    results = asyncio.run(many())
    assert len(fake.requests) == 3 and all(r is results[0] for r in results)


def test_a_failed_refresh_serves_the_last_data_as_stale(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake, clock = in_season(), Clock()
    svc = service(fake, clock)
    good = asyncio.run(svc.current())
    fake.routes["current.json"] = httpx.Response(502)
    clock.t += 700
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="app.season.service"):
        stale = asyncio.run(svc.current())
    assert stale.stale is True and good.stale is False
    assert stale.model_dump(exclude={"stale"}) == good.model_dump(exclude={"stale"})
    record = next(
        r for r in caplog.records if getattr(r, "event", None) == "season_refresh"
    )
    assert record.outcome == "error" and "HTTP 502" in record.error
    assert record.stale_age_seconds == 700

    # Within RETRY_SECONDS, no new requests; then Jolpica is asked again.
    asked = len(fake.requests)
    clock.t += RETRY_SECONDS - 1
    assert asyncio.run(svc.current()).stale is True
    assert len(fake.requests) == asked
    fake.routes["current.json"] = in_season().routes["current.json"]
    clock.t += 1
    fresh = asyncio.run(svc.current())
    assert fresh.stale is False and len(fake.requests) > asked


def test_stale_data_expires_after_a_day() -> None:
    fake, clock = in_season(), Clock()
    svc = service(fake, clock)
    asyncio.run(svc.current())
    fake.routes["current.json"] = httpx.ConnectError("down")
    clock.t += STALE_MAX_SECONDS + 1
    with pytest.raises(SeasonUnavailable):
        asyncio.run(svc.current())
    # And then it backs off, not asking on every request.
    asked = len(fake.requests)
    with pytest.raises(SeasonUnavailable):
        asyncio.run(svc.current())
    assert len(fake.requests) == asked


def test_nothing_cached_is_unavailable_with_backoff() -> None:
    fake, clock = in_season(**{"current.json": httpx.ConnectError("down")}), Clock()
    svc = service(fake, clock)
    with pytest.raises(SeasonUnavailable):
        asyncio.run(svc.current())
    asked = len(fake.requests)
    with pytest.raises(SeasonUnavailable):
        asyncio.run(svc.current())
    assert len(fake.requests) == asked
    clock.t += RETRY_SECONDS
    fake.routes["current.json"] = in_season().routes["current.json"]
    assert asyncio.run(svc.current()).season == 2026


def test_requests_identify_the_client() -> None:
    fake = in_season()
    asyncio.run(service(fake, Clock()).current())
    agent = fake.requests[0].headers["user-agent"]
    assert agent.startswith("apexgpt-backend/")
    assert str(fake.requests[0].url).startswith(BASE + "/")


# --- decided championships (F8.7) -----------------------------------------------------


def _standings(drivers_points: list[str], teams_points: list[str], rnd: int = 2):
    names = ["Antonelli", "Norris", "Leclerc"]
    teams = ["Mercedes", "McLaren", "Ferrari"]
    return {
        "current/driverStandings.json": drivers(2026, rnd, [
            driver_entry(i + 1, "X", names[i], p) for i, p in enumerate(drivers_points)
        ]),
        "current/constructorStandings.json": constructors(2026, rnd, [
            constructor_entry(i + 1, teams[i], p) for i, p in enumerate(teams_points)
        ]),
    }  # fmt: skip


# in_season(): round 2 of 3 done; round 3 (6 Dec) is a sprint weekend, so a
# driver can still score 25 + 8 = 33 and a team 43 + 15 = 58.


@pytest.mark.parametrize(
    ("driver_points", "team_points", "expected"),
    [
        (["134", "100"], ["259", "200"], ("antonelli", "mercedes")),  # 34 > 33, 59 > 58
        (["133", "100"], ["258", "200"], (None, None)),  # level is still possible
        (["120", "100"], ["300", "200"], (None, "mercedes")),
        (["150", "100"], ["210", "200"], ("antonelli", None)),
    ],
)  # fmt: skip
def test_a_title_is_decided_once_nobody_can_catch_the_leader(
    driver_points: list[str], team_points: list[str], expected: tuple
) -> None:
    snap = snapshot(in_season(**_standings(driver_points, team_points)))
    assert (snap.champions.driver_id, snap.champions.constructor_id) == expected


def test_without_a_sprint_fewer_points_are_left() -> None:
    no_sprint = calendar(2026, [race(2026, 1, "2026-03-08"),
                                race(2026, 2, "2026-11-29"),
                                race(2026, 3, "2026-12-06")])  # fmt: skip
    # 26 > 25 (no sprint), but it wouldn't be with a sprint (33).
    fake = in_season(
        **{"current.json": no_sprint}, **_standings(["126", "100"], ["1", "0"])
    )
    assert snapshot(fake).champions.driver_id == "antonelli"


def test_once_the_season_is_over_p1_is_champion() -> None:
    fake = in_season(**_standings(["101", "100"], ["201", "200"], rnd=3))
    snap = snapshot(fake, dt.datetime(2026, 12, 10, tzinfo=dt.UTC))
    assert snap.complete is True
    assert (snap.champions.driver_id, snap.champions.constructor_id) == (
        "antonelli", "mercedes",
    )  # fmt: skip


def test_last_seasons_final_standings_name_its_champions() -> None:
    fake = FakeJolpica({
        "current.json": calendar(2027, [race(2027, 1, "2027-03-07")]),
        "current/driverStandings.json": drivers(2027, None, []),
        "current/constructorStandings.json": constructors(2027, None, []),
        "2026/driverStandings.json": drivers(2026, 24, DRIVERS),
        "2026/constructorStandings.json": constructors(2026, 24, CONSTRUCTORS),
    })  # fmt: skip
    snap = snapshot(fake, dt.datetime(2027, 1, 15, tzinfo=dt.UTC))
    assert (snap.champions.driver_id, snap.champions.constructor_id) == (
        "antonelli", "mercedes",
    )  # fmt: skip


def test_no_champion_without_a_p1() -> None:
    fake = in_season(**{"current/driverStandings.json": drivers(
        2026, 2, [driver_entry(None, "Michael", "Schumacher", "500")])})  # fmt: skip
    assert snapshot(fake).champions.driver_id is None


def test_points_left_counts_races_and_sprints() -> None:
    from app.season.jolpica import Race
    from app.season.service import points_left

    plain = Race.model_validate(race(2026, 1, "2026-03-08"))
    sprint = Race.model_validate(race(2026, 2, "2026-03-15",
                                      Sprint={"date": "2026-03-14", "time": "10:00:00Z"}))  # fmt: skip
    assert points_left([]) == (0, 0)
    assert points_left([plain]) == (25, 43)
    assert points_left([plain, sprint]) == (25 + 33, 43 + 58)
