"""Integration tests for the read-only LLM role (migration 0005) on real Postgres.

Roles are cluster-wide, so these tests never change apexgpt_llm_reader's
password (that would break the developer's own READONLY_DATABASE_URL):
- privileges are tested with SET ROLE from the admin connection;
- the login path is tested on a throwaway role.

Skipped unless TEST_DATABASE_URL is set (see test_database.py for the warning).
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from app.core.config import normalise_database_url
from app.db import readonly_role
from app.db.readonly_role import ROLE, ReadonlyRoleError
from tests.conftest import make_settings

pytestmark = pytest.mark.integration

_RAW_URL = os.environ.get("TEST_DATABASE_URL")
if not _RAW_URL:
    pytest.skip("TEST_DATABASE_URL not set", allow_module_level=True)

DATABASE_URL = normalise_database_url(_RAW_URL)
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
VIEWS = {
    "v_race_winners",
    "v_driver_career",
    "v_season_summary",
    "v_head_to_head_teammates",
}
TEST_ROLE = "apexgpt_test_login_role"
TEST_PASSWORD = "test-only-password-0123456789"


def _alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.attributes["database_url"] = DATABASE_URL
    return cfg


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    eng = create_engine(DATABASE_URL, connect_args={"prepare_threshold": None})
    command.upgrade(_alembic_config(), "head")
    yield eng
    command.downgrade(_alembic_config(), "base")
    eng.dispose()


@pytest.fixture
def as_reader(engine: Engine) -> Iterator[Connection]:
    """A connection acting with the role's privileges (rolled back afterwards)."""
    with engine.connect() as conn:
        conn.execute(text(f"SET ROLE {ROLE}"))
        yield conn
        conn.rollback()
        conn.execute(text("RESET ROLE"))


def _fails(conn: Connection, sql: str) -> str:
    """Run `sql` in a savepoint; return the Postgres error class name."""
    with pytest.raises(DBAPIError) as exc, conn.begin_nested():
        conn.execute(text(sql))
    return type(exc.value.orig).__name__


# --- definition ---


def test_role_settings(engine: Engine) -> None:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT rolsuper, rolcreatedb, rolcreaterole, rolinherit, rolconnlimit, "
                "rolconfig FROM pg_roles WHERE rolname = :r"
            ),
            {"r": ROLE},
        ).one()

    assert row[:5] == (False, False, False, False, 5)
    assert set(row.rolconfig) == {
        "statement_timeout=5s",
        "lock_timeout=1s",
        "idle_in_transaction_session_timeout=10s",
        "default_transaction_read_only=on",
    }


def test_role_can_select_exactly_the_stats_views(engine: Engine) -> None:
    """Every v_* view is granted, and nothing else (catches a new view left out)."""
    with engine.connect() as conn:
        grants = conn.execute(
            text(
                "SELECT table_name, privilege_type FROM information_schema.role_table_grants "
                "WHERE grantee = :r"
            ),
            {"r": ROLE},
        ).all()
        views = set(
            conn.scalars(
                text(
                    "SELECT table_name FROM information_schema.views "
                    "WHERE table_schema = 'public' AND table_name LIKE 'v\\_%'"
                )
            )
        )

    assert views == VIEWS
    assert set(grants) == {(v, "SELECT") for v in VIEWS}


# --- what the role can and cannot do ---


@pytest.mark.parametrize("view", sorted(VIEWS))
def test_reader_can_query_the_views(as_reader: Connection, view: str) -> None:
    as_reader.execute(text(f"SELECT * FROM {view} LIMIT 1"))  # noqa: S608


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT 1 FROM results",
        "SELECT 1 FROM drivers",
        "SELECT 1 FROM driver_standings",
        "SELECT 1 FROM driver_aliases",
        "SELECT 1 FROM constructor_lineage",
        "SELECT 1 FROM alembic_version",
    ],
)
def test_reader_cannot_read_tables(as_reader: Connection, statement: str) -> None:
    assert _fails(as_reader, statement) == "InsufficientPrivilege"


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO seasons (year) VALUES (2099)",
        "UPDATE drivers SET surname = 'x'",
        "DELETE FROM results",
        "TRUNCATE results",
        "CREATE TABLE stolen (i int)",
        "CREATE VIEW v_stolen AS SELECT 1",
    ],
)
def test_reader_cannot_write_even_outside_read_only_mode(
    as_reader: Connection, statement: str
) -> None:
    """Read-only mode can be switched off by the session; privileges still block."""
    as_reader.execute(text("SET default_transaction_read_only = off"))

    assert _fails(as_reader, statement) == "InsufficientPrivilege"


def test_reader_cannot_grant_itself_access(as_reader: Connection) -> None:
    assert (
        _fails(as_reader, f"GRANT SELECT ON results TO {ROLE}")
        == "InsufficientPrivilege"
    )


# --- login path (throwaway role, so the real role's password is untouched) ---


@pytest.fixture
def test_role(engine: Engine) -> Iterator[str]:
    with engine.begin() as conn:
        conn.execute(text("DROP ROLE IF EXISTS apexgpt_test_login_role"))
        conn.execute(text("CREATE ROLE apexgpt_test_login_role NOLOGIN"))
        conn.execute(
            text("GRANT SELECT ON v_season_summary TO apexgpt_test_login_role")
        )
    yield TEST_ROLE
    with engine.begin() as conn:
        conn.execute(
            text("REVOKE SELECT ON v_season_summary FROM apexgpt_test_login_role")
        )
        conn.execute(text("DROP ROLE IF EXISTS apexgpt_test_login_role"))


def _url_as(role: str, password: str) -> str:
    url = make_url(DATABASE_URL).set(username=role, password=password)
    return url.render_as_string(hide_password=False)


def test_run_enables_login_and_checks_access(engine: Engine, test_role: str) -> None:
    settings = make_settings(
        database_url=DATABASE_URL,
        readonly_database_url=_url_as(test_role, TEST_PASSWORD),
    )

    readonly_role.run(settings, role=test_role)

    with engine.connect() as conn:
        can_login = conn.scalar(
            text("SELECT rolcanlogin FROM pg_roles WHERE rolname = :r"),
            {"r": test_role},
        )
    assert can_login is True


def test_password_with_quotes_is_set_safely(engine: Engine, test_role: str) -> None:
    password = 'it\'s-a-"quoted"-pw; DROP ROLE x; --'
    settings = make_settings(
        database_url=DATABASE_URL, readonly_database_url=_url_as(test_role, password)
    )

    readonly_role.run(settings, role=test_role)


def test_missing_role_is_reported(engine: Engine) -> None:
    with pytest.raises(ReadonlyRoleError, match="does not exist"):
        readonly_role.enable_login(engine, TEST_PASSWORD, role="apexgpt_no_such_role")
