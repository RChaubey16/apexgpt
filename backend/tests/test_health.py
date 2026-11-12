import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.api.routes import health as health_routes


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "apexgpt-backend",
        "version": __version__,
        "environment": "test",
    }


def test_health_never_touches_database(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_: object) -> bool:
        raise AssertionError("/health must not query the database")

    monkeypatch.setattr(health_routes, "check_database", fail)

    assert client.get("/health").status_code == 200


def test_health_rejects_unsupported_method(client: TestClient) -> None:
    assert client.post("/health").status_code == 405


def test_ready_ok_when_database_reachable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health_routes, "check_database", lambda _engine: True)

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_ready_503_when_database_unreachable(client: TestClient) -> None:
    # The test settings point at a port that refuses connections.
    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "unavailable"}
    # No connection details leak to the client.
    assert "127.0.0.1" not in response.text
