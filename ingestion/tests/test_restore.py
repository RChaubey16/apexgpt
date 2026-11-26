"""The restore's safety rules and table order (F7.2). No database needed;
tests/integration/test_restore_db.py restores between two real databases."""

import pytest

from restore import RestoreError, check_urls, load_order
from restore import __main__ as cli

# URLs are built here, not written out: secret scanners (GitGuardian) flag any
# literal Postgres URL with a password and a real-looking host.
FAKE_PASSWORD = "not-a-real-password"


def url(host: str, database: str = "apexgpt", query: str = "", user: str = "u") -> str:
    return f"postgresql://{user}:{FAKE_PASSWORD}@{host}/{database}" + (
        f"?{query}" if query else ""
    )


NEON_HOST = "ep-x.eu-central-1.aws.neon.tech"
LOCAL = url("localhost:5432")
NEON = url(NEON_HOST, query="sslmode=require")


@pytest.mark.parametrize(
    "target",
    [
        NEON,
        NEON.replace("require", "verify-full"),
        NEON + "&channel_binding=require",
        url("localhost:5432", "apexgpt_neon_sim"),  # local rehearsal
        url("host.docker.internal:5432", "other"),
    ],
)
def test_allowed_targets(target: str) -> None:
    check_urls(LOCAL, target)


@pytest.mark.parametrize(
    ("target", "message"),
    [
        (url("localhost", user="other"), "is the source"),
        (url("localhost:5432", query="sslmode=disable"), "is the source"),
        (url(NEON_HOST), "needs TLS"),
        (url(NEON_HOST, query="sslmode=prefer"), "needs TLS"),
    ],
)
def test_refused_targets(target: str, message: str) -> None:
    with pytest.raises(RestoreError, match=message):
        check_urls(LOCAL, target)


def test_error_messages_never_include_the_url() -> None:
    with pytest.raises(RestoreError) as info:
        check_urls(LOCAL, url(NEON_HOST))
    assert FAKE_PASSWORD not in str(info.value)


def test_parents_load_before_children() -> None:
    order = load_order(
        ["results", "races", "drivers", "seasons", "circuits", "driver_aliases"],
        [
            ("results", "races"),
            ("results", "drivers"),
            ("races", "seasons"),
            ("races", "circuits"),
            ("driver_aliases", "drivers"),
            ("chunks", "races"),  # a table not being copied is ignored
            ("drivers", "drivers"),  # self references don't block
        ],
    )
    assert order.index("races") < order.index("results")
    assert order.index("drivers") < order.index("results")
    assert order.index("seasons") < order.index("races")
    assert order == [
        "circuits",
        "drivers",
        "seasons",
        "driver_aliases",
        "races",
        "results",
    ]


def test_a_foreign_key_cycle_is_refused() -> None:
    with pytest.raises(RestoreError, match="cycle"):
        load_order(["a", "b"], [("a", "b"), ("b", "a")])


def test_cli_needs_both_urls(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("DATABASE_URL", LOCAL)
    monkeypatch.delenv("TARGET_DATABASE_URL", raising=False)
    assert cli.main([]) == 2
    assert "TARGET_DATABASE_URL is not set" in caplog.text

    monkeypatch.setenv("TARGET_DATABASE_URL", "mysql://x/y")
    assert cli.main([]) == 2
    assert "TARGET_DATABASE_URL must use a Postgres scheme" in caplog.text

    monkeypatch.setenv("TARGET_DATABASE_URL", url(NEON_HOST, "db"))
    assert cli.main([]) == 2
    assert "needs TLS" in caplog.text
    assert FAKE_PASSWORD not in caplog.text
