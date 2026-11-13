"""Settings for the Wikipedia fetcher, from the environment or the repo `.env`."""

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from structured.config import REPO_ROOT


class WikiSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    # Wikimedia's User-Agent policy asks for a client name plus contact details
    # (a URL or email), e.g. "apexgpt-fetcher/0.1 (https://github.com/you/apexgpt;
    # you@example.com)". Required before any request is made.
    wiki_user_agent: str | None = None
    # Minimum seconds between API requests (requests are always serial).
    wiki_min_interval_seconds: float = 1.0
    # Raw downloads are cached under <data_dir>/wikipedia (git-ignored).
    data_dir: Path = REPO_ROOT / "data"

    @field_validator("wiki_user_agent")
    @classmethod
    def _validate_user_agent(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if len(value) > 300 or any(c in value for c in "\r\n"):
            raise ValueError(
                "WIKI_USER_AGENT must be one line of at most 300 characters"
            )
        return value

    @field_validator("wiki_min_interval_seconds")
    @classmethod
    def _validate_interval(cls, value: float) -> float:
        if not 0.1 <= value <= 60:
            raise ValueError("WIKI_MIN_INTERVAL_SECONDS must be between 0.1 and 60")
        return value
