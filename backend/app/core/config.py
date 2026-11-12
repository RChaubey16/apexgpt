"""Application settings, loaded from environment variables (and `.env` locally).

Settings are validated at startup so misconfiguration fails fast with a clear
error instead of surfacing later at request time.
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import AnyHttpUrl, SecretStr, TypeAdapter, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

Environment = Literal["development", "production", "test"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

_url_adapter = TypeAdapter(AnyHttpUrl)

# Schemes accepted for DATABASE_URL. Neon hands out `postgresql://`, so plain
# Postgres schemes are normalised to the psycopg (v3) driver.
_POSTGRES_SCHEMES = {"postgres", "postgresql", "postgresql+psycopg"}
_DRIVER_SCHEME = "postgresql+psycopg"


def normalise_database_url(raw: str) -> str:
    """Validate a Postgres URL and force the psycopg v3 driver.

    Error messages never include the URL itself, since it contains the password.
    """
    try:
        url = make_url(raw.strip())
    except ArgumentError:
        raise ValueError("DATABASE_URL is not a valid database URL") from None
    if url.drivername not in _POSTGRES_SCHEMES:
        raise ValueError(
            f"DATABASE_URL must use a Postgres scheme ({', '.join(sorted(_POSTGRES_SCHEMES))})"
        )
    if not url.host or not url.database:
        raise ValueError("DATABASE_URL must include a host and a database name")
    return url.set(drivername=_DRIVER_SCHEME).render_as_string(hide_password=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        # Validation errors must never echo raw values: they include secrets
        # (DATABASE_URL password, API keys) and end up in startup logs.
        hide_input_in_errors=True,
    )

    app_name: str = "ApexGPT"
    environment: Environment = "development"
    log_level: LogLevel = "INFO"
    # Comma-separated in the environment, e.g. "http://localhost:3000,https://apexgpt.app"
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
    # Required. SecretStr keeps the password out of logs and reprs.
    database_url: SecretStr
    # Seconds to wait for a connection. Generous enough for a Neon cold start.
    database_connect_timeout: int = 10

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: SecretStr) -> SecretStr:
        return SecretStr(normalise_database_url(value.get_secret_value()))

    @field_validator("database_connect_timeout")
    @classmethod
    def _validate_connect_timeout(cls, value: int) -> int:
        if not 1 <= value <= 60:
            raise ValueError(
                "DATABASE_CONNECT_TIMEOUT must be between 1 and 60 seconds"
            )
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalise_log_level(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("environment", mode="before")
    @classmethod
    def _normalise_environment(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("cors_origins")
    @classmethod
    def _validate_cors_origins(cls, origins: list[str]) -> list[str]:
        for origin in origins:
            if origin == "*":
                raise ValueError(
                    "Wildcard CORS origin '*' is not allowed; list origins explicitly"
                )
            _url_adapter.validate_python(origin)
        # Browsers send Origin without a trailing slash.
        return [origin.rstrip("/") for origin in origins]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
