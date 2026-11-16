import logging
from pathlib import Path

import pytest

from narrative import embed as cli
from narrative.chunks import chunks_path
from narrative.embedder import DIMENSIONS, MODEL_NAME, content_hash
from narrative.store import StoreError, vector_literal
from structured.config import Settings


def test_content_hash_is_32_hex_and_depends_on_model_and_text() -> None:
    digest = content_hash(MODEL_NAME, "Senna and Prost collided.")

    assert len(digest) == 32
    int(digest, 16)
    assert digest == content_hash(MODEL_NAME, "Senna and Prost collided.")
    assert digest != content_hash(MODEL_NAME, "Senna and Prost collided!")
    assert digest != content_hash("other/model", "Senna and Prost collided.")
    # The separator keeps model and text apart.
    assert content_hash("ab", "c") != content_hash("a", "bc")


def test_vector_literal() -> None:
    assert vector_literal([0.5, -0.25, 1e-9], 3) == "[0.5,-0.25,1e-09]"
    assert vector_literal([1 / 3], 1) == "[0.3333333]"
    with pytest.raises(StoreError, match="2 dimensions, expected 3"):
        vector_literal([0.1, 0.2], 3)


def test_model_settings() -> None:
    assert (MODEL_NAME, DIMENSIONS) == ("BAAI/bge-small-en-v1.5", 384)


@pytest.fixture
def settings_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


def test_cli_needs_database_url(
    settings_env: Path, caplog: pytest.LogCaptureFixture
) -> None:
    assert cli.run([]) == 2
    assert "DATABASE_URL is not set" in caplog.text


def test_cli_invalid_setting(
    settings_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "mysql://user:secret@host/db")

    assert cli.run([]) == 2
    assert "Invalid setting database_url" in caplog.text
    assert "secret" not in caplog.text


def test_cli_needs_chunks_first(
    settings_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@localhost:1/db")

    assert cli.run([]) == 1
    assert "run `python -m narrative.chunk` first" in caplog.text


def test_cli_refuses_an_empty_chunks_file(
    settings_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@localhost:1/db")
    path = chunks_path(settings_env)
    path.parent.mkdir(parents=True)
    path.write_text("")
    caplog.set_level(logging.INFO)

    assert cli.run([]) == 1
    assert "chunks.jsonl is empty" in caplog.text


def test_cli_database_errors_hide_the_url(
    settings_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://user:secret@127.0.0.1:1/db?connect_timeout=1"
    )
    path = chunks_path(settings_env)
    path.parent.mkdir(parents=True)
    path.write_text(
        '{"pageid":1,"index":0,"title":"T","revid":1,"source_url":"u","section":[],'
        '"text":"x","tokens":2,"depth":"lead","kinds":["driver"]}\n'
    )

    assert cli.run([]) == 1
    assert "Database error: OperationalError" in caplog.text
    assert "secret" not in caplog.text
