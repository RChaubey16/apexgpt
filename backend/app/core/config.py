"""Application settings, loaded from environment variables (and `.env` locally).

Settings are validated at startup so misconfiguration fails fast with a clear
error instead of surfacing later at request time.
"""

from functools import lru_cache
from pathlib import Path
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
    # Optional until the SQL tool (F3.5): the read-only role the LLM's queries
    # run as (apexgpt_llm_reader). Blank means unset.
    readonly_database_url: SecretStr | None = None
    # Where the query-embedding model (bge-small, ~65 MB) is downloaded on first
    # use. Blank means fastembed's default (a temporary directory, so it is
    # downloaded again after a reboot). The ingestion pipeline uses data/models.
    embedding_cache_dir: Path | None = None
    # Threads each ONNX model (embedder, reranker) may use. ONNX Runtime
    # defaults to one per host core, but a container sees every host core while
    # its CPU quota is 1: in the dev container, reranking took 16 s instead of
    # 1.4 s. Keep it at the CPU limit (1 in docker compose and production).
    onnx_threads: int = 1

    # LLM providers (F3.3), free tiers only, tried in this order. A provider is
    # used only when its key is set; blank means unset. See app/llm/providers.py.
    groq_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    llm_groq_model: str = "openai/gpt-oss-120b"
    llm_gemini_model: str = "gemini-3.1-flash-lite"
    llm_openrouter_model: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
    # Per request, per attempt. Free tiers can be slow under load.
    llm_timeout_seconds: float = 30.0
    # Extra attempts on the same provider after a timeout, connection error or
    # 5xx, before falling back. Rate limits (429) fall back at once.
    llm_max_retries: int = 1
    # When every provider is rate limited and the limit resets within this many
    # seconds, wait once and retry (free tiers limit tokens per minute). 0 = off.
    llm_rate_limit_wait_seconds: float = 20.0

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: SecretStr) -> SecretStr:
        return SecretStr(normalise_database_url(value.get_secret_value()))

    @field_validator("readonly_database_url")
    @classmethod
    def _validate_readonly_database_url(
        cls, value: SecretStr | None
    ) -> SecretStr | None:
        if value is None or not value.get_secret_value().strip():
            return None
        return SecretStr(normalise_database_url(value.get_secret_value()))

    @field_validator("embedding_cache_dir", mode="before")
    @classmethod
    def _blank_cache_dir_is_unset(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("embedding_cache_dir")
    @classmethod
    def _validate_cache_dir(cls, value: Path | None) -> Path | None:
        if value is not None and value.exists() and not value.is_dir():
            raise ValueError("EMBEDDING_CACHE_DIR must be a directory")
        return value

    @field_validator(
        "groq_api_key", "gemini_api_key", "openrouter_api_key", mode="before"
    )
    @classmethod
    def _blank_key_is_unset(cls, value: object) -> object:
        raw = value.get_secret_value() if isinstance(value, SecretStr) else value
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return None
        return raw.strip() if isinstance(raw, str) else raw

    @field_validator("llm_groq_model", "llm_gemini_model", "llm_openrouter_model")
    @classmethod
    def _validate_model_name(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 200 or any(c.isspace() for c in value):
            raise ValueError("LLM model names must be non-empty with no spaces")
        return value

    @field_validator("llm_timeout_seconds")
    @classmethod
    def _validate_llm_timeout(cls, value: float) -> float:
        if not 1 <= value <= 120:
            raise ValueError("LLM_TIMEOUT_SECONDS must be between 1 and 120")
        return value

    @field_validator("llm_rate_limit_wait_seconds")
    @classmethod
    def _validate_rate_limit_wait(cls, value: float) -> float:
        if not 0 <= value <= 60:
            raise ValueError("LLM_RATE_LIMIT_WAIT_SECONDS must be between 0 and 60")
        return value

    @field_validator("llm_max_retries")
    @classmethod
    def _validate_llm_retries(cls, value: int) -> int:
        if not 0 <= value <= 3:
            raise ValueError("LLM_MAX_RETRIES must be between 0 and 3")
        return value

    @field_validator("onnx_threads")
    @classmethod
    def _validate_onnx_threads(cls, value: int) -> int:
        if not 1 <= value <= 16:
            raise ValueError("ONNX_THREADS must be between 1 and 16")
        return value

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
