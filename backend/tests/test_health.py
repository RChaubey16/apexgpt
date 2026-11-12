from fastapi.testclient import TestClient

from app import __version__


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "apexgpt-backend",
        "version": __version__,
        "environment": "test",
    }


def test_health_rejects_unsupported_method(client: TestClient) -> None:
    response = client.post("/health")

    assert response.status_code == 405
