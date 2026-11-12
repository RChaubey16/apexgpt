import pytest
from pydantic import ValidationError

from app.core.config import Settings
from tests.conftest import make_settings


def test_defaults() -> None:
    settings = make_settings()

    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.cors_origins == ["http://localhost:3000"]
    assert settings.is_production is False


def test_reads_values_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "Production")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000, https://apexgpt.app/")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.example.com/apex")

    settings = Settings(_env_file=None)

    assert settings.environment == "production"
    assert settings.is_production is True
    assert settings.log_level == "DEBUG"
    assert settings.cors_origins == ["http://localhost:3000", "https://apexgpt.app"]


def test_empty_entries_in_cors_list_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000,, ")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/apex")

    assert Settings(_env_file=None).cors_origins == ["http://localhost:3000"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("environment", "staging"),
        ("log_level", "VERBOSE"),
        ("cors_origins", ["*"]),
        ("cors_origins", ["not-a-url"]),
        ("cors_origins", ["ftp://example.com"]),
        ("database_connect_timeout", 0),
        ("database_connect_timeout", 61),
    ],
)
def test_invalid_values_fail_fast(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        make_settings(**{field: value})


# --- DATABASE_URL ---


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    "raw",
    [
        "postgres://u:p@host:5432/apex",
        "postgresql://u:p@host:5432/apex",
        "postgresql+psycopg://u:p@host:5432/apex",
    ],
)
def test_database_url_normalised_to_psycopg(raw: str) -> None:
    url = make_settings(database_url=raw).database_url.get_secret_value()

    assert url == "postgresql+psycopg://u:p@host:5432/apex"


def test_database_url_keeps_query_params() -> None:
    raw = "postgresql://u:p@ep-x.neon.tech/apex?sslmode=require"

    url = make_settings(database_url=raw).database_url.get_secret_value()

    assert url == "postgresql+psycopg://u:p@ep-x.neon.tech/apex?sslmode=require"


@pytest.mark.parametrize(
    "raw",
    [
        "mysql://u:p@host/apex",
        "sqlite:///apex.db",
        "postgresql://u:p@host",  # no database name
        "postgresql:///apex",  # no host
        "not a url",
    ],
)
def test_invalid_database_url_rejected(raw: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(database_url=raw)


def test_database_password_never_exposed() -> None:
    settings = make_settings(database_url="postgresql://u:s3cret-pw@host/apex")

    assert "s3cret-pw" not in repr(settings)
    assert "s3cret-pw" not in str(settings.model_dump())


def test_invalid_database_url_error_hides_password() -> None:
    with pytest.raises(ValidationError) as exc_info:
        make_settings(database_url="mysql://u:s3cret-pw@host/apex")

    assert "s3cret-pw" not in str(exc_info.value)
