import datetime as dt
from decimal import Decimal

import pytest

from structured.errors import DumpError
from structured.transform import F1Data, duration_ms, transform
from tests.fixture_dump import FakeSource, tables


@pytest.fixture
def data() -> F1Data:
    return transform(FakeSource(), first_season=1950, last_season=2025)


def _by(rows: list[dict], **match: object) -> dict:
    found = [r for r in rows if all(r[k] == v for k, v in match.items())]
    assert len(found) == 1, (match, found)
    return found[0]


# --- durations ---


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("02:13:23.6", 8_003_600),
        ("00:01:16.29", 76_290),
        ("00:00:24.036", 24_036),
        ("01:32:03.897", 5_523_897),
        ("00:51:09.017", 3_069_017),
        ("00:00:01", 1_000),
        ("00:00:00.0005", 1),
    ],
)
def test_duration_ms(value: str, expected: int) -> None:
    assert duration_ms(value) == expected


@pytest.mark.parametrize(
    "value", ["", "1:32.5", "00:61:00", "00:00:60", "abc", "-00:00:01"]
)
def test_duration_ms_rejects_bad_formats(value: str) -> None:
    assert duration_ms(value) is None


# --- scope ---


def test_counts(data: F1Data) -> None:
    assert data.counts() == {
        "seasons": 2,
        "circuits": 2,
        "drivers": 2,
        "constructors": 2,
        "status": 3,
        "races": 2,
        "results": 5,
        "sprint_results": 2,
        "qualifying": 4,
        "driver_standings": 4,
        "constructor_standings": 2,
        "pit_stops": 1,
    }


def test_cancelled_future_and_out_of_range_rounds_are_skipped(data: F1Data) -> None:
    assert {r["race_id"] for r in data.races} == {1, 4}
    # Round 3 (no results yet) is reported as skipped; cancelled round 2 is not a race.
    assert data.skipped_races == 1


def test_entities_are_limited_to_referenced_rows(data: F1Data) -> None:
    assert {d["driver_id"] for d in data.drivers} == {1, 2}
    assert {c["constructor_id"] for c in data.constructors} == {1, 2}
    assert {c["circuit_id"] for c in data.circuits} == {1, 2}
    assert [s["year"] for s in data.seasons] == [2020, 2021]


def test_season_range_filters_everything() -> None:
    data = transform(FakeSource(), first_season=2021, last_season=2021)

    assert {r["season"] for r in data.races} == {2021}
    assert all(r["race_id"] == 1 for r in data.results + data.qualifying)
    assert [s["year"] for s in data.seasons] == [2021]


@pytest.mark.parametrize(("first", "last"), [(1949, 2025), (2025, 2024), (1950, 2101)])
def test_invalid_season_range(first: int, last: int) -> None:
    with pytest.raises(ValueError, match="season range"):
        transform(FakeSource(), first_season=first, last_season=last)


# --- entities ---


def test_entity_fields(data: F1Data) -> None:
    assert _by(data.drivers, driver_id=1) == {
        "driver_id": 1,
        "ref": "hamilton",
        "code": "HAM",
        "number": 44,
        "forename": "Lewis",
        "surname": "Hamilton",
        "date_of_birth": dt.date(1985, 1, 7),
        "nationality": "British",
        "wikipedia_url": "http://en.wikipedia.org/wiki/Lewis_Hamilton",
    }
    circuit = _by(data.circuits, circuit_id=2)
    assert (
        circuit["ref"],
        circuit["lat"],
        circuit["altitude"],
        circuit["wikipedia_url"],
    ) == (
        "red_bull_ring",
        47.2197,
        678,
        None,
    )
    assert _by(data.races, race_id=1) == {
        "race_id": 1,
        "season": 2021,
        "round": 1,
        "name": "Bahrain Grand Prix",
        "circuit_id": 1,
        "date": dt.date(2021, 3, 28),
        "wikipedia_url": "https://en.wikipedia.org/wiki/2021_Bahrain_Grand_Prix",
    }


# --- results ---


def test_classified_result(data: F1Data) -> None:
    winner = _by(data.results, result_id=100)

    assert winner == {
        "result_id": 100,
        "race_id": 1,
        "driver_id": 2,
        "constructor_id": 2,
        "number": 33,
        "grid": 2,
        "position": 1,
        "position_order": 1,
        "points": Decimal("25.00"),
        "laps": 56,
        "time_ms": 5_523_897,
        "fastest_lap_rank": 1,
        "fastest_lap_number": 44,
        "fastest_lap_ms": 92_090,
        "status": "Finished",
    }


def test_unclassified_result(data: F1Data) -> None:
    retired = _by(data.results, result_id=101)

    assert retired["position"] is None
    assert retired["position_order"] == 2
    assert retired["time_ms"] is None
    # Status code 11 with no detail text falls back to the enum name.
    assert retired["status"] == "Retired"
    # Rank 0 means "no timed lap"; the deleted fastest lap is ignored.
    assert retired["fastest_lap_rank"] is None
    assert retired["fastest_lap_ms"] is None


def test_shared_drive_and_split_points(data: F1Data) -> None:
    race = [r for r in data.results if r["race_id"] == 4]

    assert sorted(
        (r["driver_id"], r["constructor_id"], r["position"]) for r in race
    ) == [
        (1, 1, 1),
        (1, 2, 3),
        (2, 2, 1),
    ]
    assert _by(race, result_id=140)["points"] == Decimal("4.50")
    # Float artefact 1.1400000000000001 rounds to 1.14.
    assert _by(race, result_id=142)["points"] == Decimal("1.14")
    assert _by(race, result_id=142)["status"] == "+1 Lap"


def test_sprint_results(data: F1Data) -> None:
    sprint = _by(data.sprint_results, sprint_result_id=110)

    assert (sprint["driver_id"], sprint["position"], sprint["points"]) == (
        1,
        1,
        Decimal("3.00"),
    )
    assert sprint["time_ms"] == 1_538_426
    assert "fastest_lap_rank" not in sprint


def test_statuses_are_distinct_texts(data: F1Data) -> None:
    assert data.statuses == ["+1 Lap", "Finished", "Retired"]


# --- qualifying ---


def test_knockout_qualifying(data: F1Data) -> None:
    ver = _by(data.qualifying, race_id=1, driver_id=2)
    ham = _by(data.qualifying, race_id=1, driver_id=1)

    # Position comes from the last session (Q3), not the best across sessions.
    assert (ver["position"], ham["position"]) == (1, 2)
    assert (ver["q1_ms"], ver["q2_ms"], ver["q3_ms"]) == (90_500, 90_300, 89_385)
    assert (ham["q1_ms"], ham["q2_ms"], ham["q3_ms"]) == (91_000, 90_200, 89_600)
    assert ver["constructor_id"] == 2 and ver["number"] == 33


def test_two_session_qualifying_and_shared_entries(data: F1Data) -> None:
    ham = _by(data.qualifying, race_id=4, driver_id=1)
    ver = _by(data.qualifying, race_id=4, driver_id=2)

    # Two QB sessions fill q1 then q2; position from the last session.
    assert (ham["position"], ham["q1_ms"], ham["q2_ms"], ham["q3_ms"]) == (
        2,
        63_000,
        62_939,
        None,
    )
    assert (ver["position"], ver["q1_ms"], ver["q2_ms"]) == (1, 63_500, 62_900)
    # Hamilton's second car (P3) is dropped: one row per driver, best car kept.
    assert ham["constructor_id"] == 1


# --- standings and pit stops ---


def test_driver_standings(data: F1Data) -> None:
    assert _by(data.driver_standings, race_id=1, driver_id=2) == {
        "race_id": 1,
        "driver_id": 2,
        "points": Decimal("25.00"),
        "position": 1,
        "wins": 1,
    }
    # Disqualified from the championship (adjustment 101) and ineligible: no position.
    assert _by(data.driver_standings, race_id=4, driver_id=1)["position"] is None
    assert _by(data.driver_standings, race_id=4, driver_id=2)["position"] is None


def test_constructor_standings(data: F1Data) -> None:
    assert _by(data.constructor_standings, race_id=1, constructor_id=2)[
        "points"
    ] == Decimal("27.00")


def test_pit_stops(data: F1Data) -> None:
    assert data.pit_stops == [
        {
            "race_id": 1,
            "driver_id": 2,
            "stop": 1,
            "lap": 20,
            "local_time": dt.time(18, 35, 12),
            "duration_ms": 22_500,
        }
    ]


# --- bad data fails loudly ---


def _transform_with(**changes: dict[str, str]) -> None:
    data = tables()
    for key, values in changes.items():
        table, row_id = key.rsplit("_", 1)
        _by(data[table], id=row_id).update(values)
    transform(FakeSource(data))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"sessionentry_100": {"points": "abc"}}, "'points' is not a valid number"),
        ({"sessionentry_100": {"points": "1.234"}}, "more than 2 decimal places"),
        ({"sessionentry_100": {"grid": ""}}, "'grid' is required"),
        ({"sessionentry_100": {"is_classified": "yes"}}, "not a boolean"),
        ({"sessionentry_100": {"time": "1h32m"}}, "not a duration"),
        ({"sessionentry_101": {"status": "99"}}, "unknown status code"),
        ({"sessionentry_100": {"round_entry_id": "999"}}, "unknown round entry"),
        ({"round_1": {"date": "28/03/2021"}}, "not an ISO date"),
        ({"round_1": {"season_id": "99"}}, "unknown season"),
        ({"round_3": {"number": "1"}}, "races: duplicate season, round"),
        ({"driver_1": {"abbreviation": "HA"}}, "must be 3 characters"),
        ({"pitstop_1": {"lap_id": "999"}}, "unknown laps"),
        ({"pitstop_1": {"duration": ""}}, "'duration' is required"),
    ],
)
def test_bad_values_raise_dump_error(changes: dict, message: str) -> None:
    with pytest.raises(DumpError, match=message):
        _transform_with(**changes)


def test_missing_referenced_entity() -> None:
    data = tables()
    data["driver"] = [d for d in data["driver"] if d["id"] != "2"]

    with pytest.raises(DumpError, match="referenced driver rows are missing"):
        transform(FakeSource(data))


def test_missing_required_column() -> None:
    data = tables()
    for row in data["sessionentry"]:
        del row["grid"]

    with pytest.raises(DumpError, match="'sessionentry' is missing columns: grid"):
        transform(FakeSource(data))


def test_error_names_table_and_row() -> None:
    with pytest.raises(DumpError, match=r"sessionentry row id=100: column 'points'"):
        _transform_with(sessionentry_100={"points": "x"})
