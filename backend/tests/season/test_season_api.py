"""GET /api/season/current (F8.3), with the service on a fake Jolpica."""

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.routes.season import UNAVAILABLE
from app.main import create_app
from app.season.service import SeasonService
from tests.conftest import make_settings
from tests.season.fakes import FakeJolpica, in_season


def client_for(fake: FakeJolpica, **settings: object) -> TestClient:
    app = create_app(make_settings(environment="test", **settings))
    app.state.season_service = SeasonService(
        "https://api.jolpi.ca/ergast/f1", 600, transport=fake.transport
    )
    return TestClient(app)


def test_current_season() -> None:
    response = client_for(in_season()).get("/api/season/current")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=60"
    body = response.json()
    assert set(body) == {
        "season", "round", "total_rounds", "complete", "drivers", "constructors",
        "next_race", "champions", "fetched_at", "stale",
    }  # fmt: skip
    # fakes.in_season(): leads of 102.5 and 166 with 33 and 58 points left.
    assert body["champions"] == {"driver_id": "antonelli", "constructor_id": "mercedes"}
    assert body["drivers"][0] == {
        "position": 1, "position_text": "1", "driver_id": "antonelli",
        "code": "ANT", "number": 44, "given_name": "Kimi",
        "family_name": "Antonelli", "nationality": "British",
        "team": "Mercedes", "team_id": "mercedes", "points": 402.5, "wins": 9,
    }  # fmt: skip
    assert body["constructors"][0]["name"] == "Mercedes"
    race = body["next_race"]
    assert race["circuit"] == {"circuit_id": "circuit_2", "name": "Circuit 2",
                               "locality": "Town", "country": "Country"}  # fmt: skip
    assert race["sessions"][-1]["kind"] == "race"
    assert race["start"].startswith("2026-11-29T16:00:00")


def test_unavailable_is_a_safe_503() -> None:
    fake = in_season(**{"current.json": httpx.ConnectError("api.jolpi.ca refused")})
    response = client_for(fake).get("/api/season/current")
    assert response.status_code == 503
    assert response.json() == {"detail": UNAVAILABLE}
    assert response.headers["cache-control"] == "no-store"
    assert "jolpi" not in response.text


def test_rate_limited() -> None:
    client = client_for(in_season(), rate_limit_season="2/minute")
    assert [client.get("/api/season/current").status_code for _ in range(3)] == [
        200, 200, 429,
    ]  # fmt: skip


def test_only_get() -> None:
    assert client_for(in_season()).post("/api/season/current").status_code == 405


def test_app_builds_the_service_from_settings() -> None:
    app = create_app(make_settings(environment="test",
                                   jolpica_base_url="https://example.test/f1/"))  # fmt: skip
    service = app.state.season_service
    assert isinstance(service, SeasonService)
    assert service._base_url == "https://example.test/f1/"


@pytest.mark.parametrize(
    ("field", "value"),
    [("season_cache_ttl_seconds", 59), ("season_cache_ttl_seconds", 3601),
     ("jolpica_base_url", "ftp://example.test"), ("jolpica_base_url", "nope"),
     ("rate_limit_season", "lots")],
)  # fmt: skip
def test_bad_season_settings_fail_at_startup(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        make_settings(**{field: value})


def test_season_defaults() -> None:
    s = make_settings()
    assert s.jolpica_base_url == "https://api.jolpi.ca/ergast/f1"
    assert s.season_cache_ttl_seconds == 600
    assert s.rate_limit_season == "60/minute;2000/day"
