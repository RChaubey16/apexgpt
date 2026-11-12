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

    settings = Settings(_env_file=None)

    assert settings.environment == "production"
    assert settings.is_production is True
    assert settings.log_level == "DEBUG"
    assert settings.cors_origins == ["http://localhost:3000", "https://apexgpt.app"]


def test_empty_entries_in_cors_list_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000,, ")

    assert Settings(_env_file=None).cors_origins == ["http://localhost:3000"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("environment", "staging"),
        ("log_level", "VERBOSE"),
        ("cors_origins", ["*"]),
        ("cors_origins", ["not-a-url"]),
        ("cors_origins", ["ftp://example.com"]),
    ],
)
def test_invalid_values_fail_fast(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        make_settings(**{field: value})
