from pathlib import Path

import pytest
from pydantic import ValidationError

from structured import __main__ as cli
from structured.config import Settings, normalise_database_url
from tests.fixture_dump import write_zip


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never read the developer's real .env or DATABASE_URL."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.delenv("DATABASE_URL", raising=False)


# --- config ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "postgresql://u:p@localhost:5432/apex",
            "postgresql://u:p@localhost:5432/apex",
        ),
        ("postgres://u:p@db.example.com/apex", "postgresql://u:p@db.example.com/apex"),
        (
            "postgresql+psycopg://u:p@host/apex?sslmode=require",
            "postgresql://u:p@host/apex?sslmode=require",
        ),
    ],
)
def test_database_url_is_normalised(raw: str, expected: str) -> None:
    assert normalise_database_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "mysql://u:secret@host/db",
        "postgresql://u:secret@/db",
        "postgresql://u:secret@host",
    ],
)
def test_invalid_database_url_error_hides_the_password(
    raw: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", raw)

    with pytest.raises(ValidationError) as exc:
        Settings()
    assert "secret" not in str(exc.value)


def test_blank_database_url_means_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "  ")

    assert Settings().database_url is None


@pytest.mark.parametrize("timeout", ["0", "61"])
def test_connect_timeout_range(timeout: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_CONNECT_TIMEOUT", timeout)

    with pytest.raises(ValidationError):
        Settings()


# --- CLI ---


def test_dry_run_prints_counts_without_a_database(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dump = write_zip(tmp_path / "dump.zip")

    assert cli.run(["--dump", str(dump), "--dry-run"]) == 0

    out = capsys.readouterr().out
    assert "results" in out and "5" in out


def test_load_without_database_url_fails_clearly(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    dump = write_zip(tmp_path / "dump.zip")

    assert cli.run(["--dump", str(dump)]) == 2
    assert "DATABASE_URL is not set" in caplog.text


def test_bad_dump_is_reported_without_traceback(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    dump = tmp_path / "dump.zip"
    dump.write_text("not a zip")

    assert cli.run(["--dump", str(dump), "--dry-run"]) == 1
    assert "not a readable zip" in caplog.text


def test_unreachable_database_is_reported_without_the_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Port 1 refuses connections immediately.
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:topsecret@127.0.0.1:1/apex")
    monkeypatch.setenv("DATABASE_CONNECT_TIMEOUT", "1")
    dump = write_zip(tmp_path / "dump.zip")

    assert cli.run(["--dump", str(dump)]) == 1
    assert "Database connection failed" in caplog.text
    assert "topsecret" not in caplog.text


@pytest.mark.parametrize(
    "args",
    [
        ["--first-season", "1949"],
        ["--first-season", "2025", "--last-season", "2024"],
        ["--dump", "/nonexistent/dump.zip"],
    ],
)
def test_invalid_arguments_exit(args: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.run(args)
    assert exc.value.code == 2
