"""Integration tests against a real Postgres + pgvector database.

Skipped unless TEST_DATABASE_URL is set, e.g.:

    docker compose up -d db
    TEST_DATABASE_URL=postgresql://apexgpt:change-me@localhost:5432/apexgpt \
        uv run pytest -m integration

WARNING: these tests run migrations up and down. Never point TEST_DATABASE_URL
at a database holding real data.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text

from app.core.config import normalise_database_url
from app.main import create_app
from tests.conftest import make_settings

pytestmark = pytest.mark.integration

_RAW_URL = os.environ.get("TEST_DATABASE_URL")
if not _RAW_URL:
    pytest.skip("TEST_DATABASE_URL not set", allow_module_level=True)

DATABASE_URL = normalise_database_url(_RAW_URL)
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def _alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.attributes["database_url"] = DATABASE_URL
    return cfg


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine(DATABASE_URL, connect_args={"prepare_threshold": None})
    yield eng
    eng.dispose()


@pytest.fixture
def migrated(engine: Engine) -> Iterator[Engine]:
    command.upgrade(_alembic_config(), "head")
    yield engine
    command.downgrade(_alembic_config(), "base")


def _vector_version(engine: Engine) -> str | None:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        ).scalar_one_or_none()


def test_upgrade_enables_pgvector_with_halfvec_support(migrated: Engine) -> None:
    version = _vector_version(migrated)

    assert version is not None
    major, minor = (int(part) for part in version.split(".")[:2])
    assert (major, minor) >= (0, 7), f"halfvec needs pgvector >= 0.7, got {version}"

    with migrated.connect() as conn:
        distance = conn.execute(
            text("SELECT '[1,0,0]'::halfvec(3) <=> '[0,1,0]'::halfvec(3)")
        ).scalar_one()
    assert distance == pytest.approx(1.0)


def test_upgrade_is_idempotent(migrated: Engine) -> None:
    command.upgrade(_alembic_config(), "head")

    assert _vector_version(migrated) is not None


def test_downgrade_removes_pgvector(engine: Engine) -> None:
    command.upgrade(_alembic_config(), "head")
    command.downgrade(_alembic_config(), "base")

    assert _vector_version(engine) is None


def test_server_is_postgres_18(engine: Engine) -> None:
    """Local DB must match Neon's default major version."""
    with engine.connect() as conn:
        version_num = int(conn.execute(text("SHOW server_version_num")).scalar_one())

    assert version_num // 10000 == 18


def test_ready_endpoint_against_real_database() -> None:
    client = TestClient(create_app(make_settings(database_url=DATABASE_URL)))

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
