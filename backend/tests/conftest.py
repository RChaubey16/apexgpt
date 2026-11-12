import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

# Port 1 on localhost refuses connections immediately: a safe "unreachable DB"
# for unit tests that must never touch a real database.
UNREACHABLE_DATABASE_URL = "postgresql://test:test@127.0.0.1:1/test"


def make_settings(**overrides: object) -> Settings:
    """Settings isolated from the developer's real `.env` file."""
    values: dict[str, object] = {
        "database_url": UNREACHABLE_DATABASE_URL,
        "database_connect_timeout": 1,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def settings() -> Settings:
    return make_settings(environment="test")


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))
