"""Settings for the structured-data loader, from the environment or the repo `.env`."""

from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

# Accepted DATABASE_URL schemes. psycopg (libpq) only understands the plain
# `postgresql://` form, so the others are rewritten to it.
_POSTGRES_SCHEMES = {"postgres", "postgresql", "postgresql+psycopg"}


def normalise_database_url(raw: str) -> str:
    """Validate a Postgres URL and return it in libpq form (`postgresql://`).

    Error messages never include the URL itself, since it contains the password.
    """
    try:
        parts = urlsplit(raw.strip())
    except ValueError:
        raise ValueError("DATABASE_URL is not a valid URL") from None
    if parts.scheme not in _POSTGRES_SCHEMES:
        raise ValueError(
            f"DATABASE_URL must use a Postgres scheme ({', '.join(sorted(_POSTGRES_SCHEMES))})"
        )
    if not parts.hostname or not parts.path.strip("/"):
        raise ValueError("DATABASE_URL must include a host and a database name")
    return urlunsplit(parts._replace(scheme="postgresql"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Run from ingestion/ (or the repo root): both find the repo's .env.
        env_file=(REPO_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        # Never echo raw values (DATABASE_URL holds a password) in errors.
        hide_input_in_errors=True,
    )

    # Required for loading (not for --dry-run). The backend's host-side URL.
    database_url: SecretStr | None = None
    # Seconds to wait when connecting. Covers a Neon cold start.
    database_connect_timeout: int = 10
    # Raw downloads are cached here (git-ignored).
    data_dir: Path = REPO_ROOT / "data"

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None or not value.get_secret_value().strip():
            return None
        return SecretStr(normalise_database_url(value.get_secret_value()))

    @field_validator("database_connect_timeout")
    @classmethod
    def _validate_connect_timeout(cls, value: int) -> int:
        if not 1 <= value <= 60:
            raise ValueError(
                "DATABASE_CONNECT_TIMEOUT must be between 1 and 60 seconds"
            )
        return value
