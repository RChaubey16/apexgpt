from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings


def test_unhandled_error_returns_generic_500_without_details() -> None:
    app = create_app(make_settings(environment="test"))

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret internal detail")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/boom")

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert "secret internal detail" not in response.text


def test_unknown_route_returns_404(client: TestClient) -> None:
    assert client.get("/does-not-exist").status_code == 404


def test_docs_enabled_outside_production(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_docs_disabled_in_production() -> None:
    client = TestClient(create_app(make_settings(environment="production")))

    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_cors_allows_configured_origin() -> None:
    client = TestClient(
        create_app(make_settings(cors_origins=["http://localhost:3000"]))
    )

    response = client.get("/health", headers={"Origin": "http://localhost:3000"})

    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_rejects_unknown_origin() -> None:
    client = TestClient(
        create_app(make_settings(cors_origins=["http://localhost:3000"]))
    )

    response = client.get("/health", headers={"Origin": "https://evil.example"})

    assert "access-control-allow-origin" not in response.headers
