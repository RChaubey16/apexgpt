"""The API domain's favicon (F8.1)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.routes import favicon as favicon_route
from app.main import create_app
from tests.conftest import make_settings

ICO_HEADER = b"\x00\x00\x01\x00"  # reserved, type 1 (icon)


def test_favicon_is_served(client: TestClient) -> None:
    response = client.get("/favicon.ico")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/x-icon"
    assert response.headers["cache-control"] == "public, max-age=86400"
    assert response.content.startswith(ICO_HEADER)
    assert response.content == favicon_route.FAVICON.read_bytes()


def test_favicon_is_not_in_the_api_docs(client: TestClient) -> None:
    assert "/favicon.ico" not in client.get("/openapi.json").json()["paths"]


def test_favicon_is_not_rate_limited() -> None:
    client = TestClient(
        create_app(make_settings(environment="test", rate_limit_chat="1/minute"))
    )
    assert {client.get("/favicon.ico").status_code for _ in range(20)} == {200}


def test_a_missing_favicon_is_a_plain_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(favicon_route, "FAVICON", tmp_path / "missing.ico")
    response = client.get("/favicon.ico")
    assert response.status_code == 404


def test_the_favicon_ships_with_the_app_package() -> None:
    # The runtime image copies backend/app only, so the file must live there.
    assert favicon_route.FAVICON.is_relative_to(
        Path(__file__).resolve().parents[1] / "app"
    )
