"""Unit tests for the read-only role setup command (no database needed)."""

import pytest
from pydantic import ValidationError

from app.db import readonly_role
from app.db.readonly_role import ROLE, ReadonlyRoleError, credentials
from tests.conftest import make_settings

GOOD_PASSWORD = "x" * readonly_role.MIN_PASSWORD_LENGTH


def test_credentials_returns_the_password() -> None:
    url = f"postgresql://{ROLE}:{GOOD_PASSWORD}@localhost/apex"

    assert credentials(url) == GOOD_PASSWORD


@pytest.mark.parametrize(
    ("url", "message"),
    [
        (
            f"postgresql://apexgpt:{GOOD_PASSWORD}@localhost/apex",
            f"must connect as {ROLE}",
        ),
        (f"postgresql://{ROLE}@localhost/apex", "password of at least"),
        (f"postgresql://{ROLE}:short@localhost/apex", "password of at least"),
    ],
)
def test_bad_credentials_are_rejected(url: str, message: str) -> None:
    with pytest.raises(ReadonlyRoleError, match=message) as exc:
        credentials(url)
    assert GOOD_PASSWORD not in str(exc.value)
    assert "short" not in str(exc.value)


def test_readonly_url_is_optional_and_blank_means_unset() -> None:
    assert make_settings().readonly_database_url is None
    assert make_settings(readonly_database_url="  ").readonly_database_url is None


def test_readonly_url_is_normalised_and_secret() -> None:
    settings = make_settings(
        readonly_database_url=f"postgresql://{ROLE}:{GOOD_PASSWORD}@db/apex"
    )

    assert settings.readonly_database_url is not None
    value = settings.readonly_database_url.get_secret_value()
    assert value.startswith("postgresql+psycopg://")
    assert GOOD_PASSWORD not in repr(settings)


def test_invalid_readonly_url_error_hides_the_password() -> None:
    with pytest.raises(ValidationError) as exc:
        make_settings(readonly_database_url="mysql://u:topsecret@host/db")
    assert "topsecret" not in str(exc.value)


def test_run_without_readonly_url_fails_clearly() -> None:
    with pytest.raises(ReadonlyRoleError, match="READONLY_DATABASE_URL is not set"):
        readonly_role.run(make_settings())


def test_main_reports_errors_without_traceback(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(readonly_role, "Settings", lambda: make_settings())

    assert readonly_role.main() == 1
    assert "READONLY_DATABASE_URL is not set" in caplog.text


def test_main_hides_database_error_details(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The admin DB is unreachable (port 1): only the error class is shown."""
    settings = make_settings(
        readonly_database_url=f"postgresql://{ROLE}:{GOOD_PASSWORD}@127.0.0.1:1/apex"
    )
    monkeypatch.setattr(readonly_role, "Settings", lambda: settings)

    assert readonly_role.main() == 1
    assert "Database error: OperationalError" in caplog.text
    assert GOOD_PASSWORD not in caplog.text
    assert "127.0.0.1" not in caplog.text
