from pathlib import Path

import pytest

from common import size_guard
from common.size_guard import MB, REFUSE_BYTES, WARN_BYTES, SizeGuard
from structured.config import Settings


def test_budget_matches_the_data_strategy() -> None:
    # docs/DATA-STRATEGY.md §4: warn at 700 MB, refuse at 900 MB (Neon: 1 GB).
    assert (WARN_BYTES, REFUSE_BYTES) == (700 * MB, 900 * MB)
    assert SizeGuard() == SizeGuard(WARN_BYTES, REFUSE_BYTES)


@pytest.mark.parametrize(("warn", "refuse"), [(0, 10), (10, 5), (-1, 5)])
def test_rejects_bad_thresholds(warn: int, refuse: int) -> None:
    with pytest.raises(ValueError, match="need 0 < warn_bytes <= refuse_bytes"):
        SizeGuard(warn, refuse)


@pytest.fixture
def no_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))


def test_cli_needs_database_url(no_env: None, caplog: pytest.LogCaptureFixture) -> None:
    assert size_guard.run([]) == 2
    assert "DATABASE_URL is not set" in caplog.text


def test_cli_hides_the_url_on_errors(
    no_env: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@127.0.0.1:1/db")
    monkeypatch.setenv("DATABASE_CONNECT_TIMEOUT", "1")

    assert size_guard.run([]) == 1
    assert "Database error: OperationalError" in caplog.text
    assert "secret" not in caplog.text
