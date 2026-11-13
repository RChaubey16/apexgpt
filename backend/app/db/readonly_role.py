"""Enable login for the read-only LLM role, using READONLY_DATABASE_URL.

    cd backend && uv run python -m app.db.readonly_role
    docker compose exec backend python -m app.db.readonly_role

Migration 0005 creates `apexgpt_llm_reader` with no password (NOLOGIN), so no
credential lives in migrations. This command connects with the admin
DATABASE_URL, sets the password from READONLY_DATABASE_URL, enables LOGIN, then
connects as the role to check it can read a stats view. Re-run it to rotate the
password. It never prints either URL or password.
"""

import logging
import sys

from psycopg import sql
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.db.session import create_db_engine

logger = logging.getLogger(__name__)

ROLE = "apexgpt_llm_reader"
# Neon requires passwords with at least 60 bits of entropy.
MIN_PASSWORD_LENGTH = 16


class ReadonlyRoleError(Exception):
    """Expected, user-facing failure (printed without a traceback)."""


def credentials(readonly_url: str, role: str = ROLE) -> str:
    """Validate READONLY_DATABASE_URL and return its password."""
    url = make_url(readonly_url)
    if url.username != role:
        raise ReadonlyRoleError(f"READONLY_DATABASE_URL must connect as {role}")
    if not url.password or len(url.password) < MIN_PASSWORD_LENGTH:
        raise ReadonlyRoleError(
            f"READONLY_DATABASE_URL needs a password of at least {MIN_PASSWORD_LENGTH} characters"
        )
    return url.password


def enable_login(admin_engine: Engine, password: str, role: str = ROLE) -> None:
    """Set the role's password and allow it to log in."""
    with admin_engine.begin() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}
        ).scalar()
        if not exists:
            raise ReadonlyRoleError(
                f"role {role} does not exist: run `alembic upgrade head` first"
            )
        # ALTER ROLE takes no bind parameters: quote the password as a literal.
        statement = sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(
            sql.Identifier(role), sql.Literal(password)
        )
        raw = conn.connection.driver_connection
        with raw.cursor() as cur:
            cur.execute(statement)


def check_access(readonly_url: str, connect_timeout: int) -> None:
    """Connect as the role and read one row from a stats view."""
    engine = create_engine(
        readonly_url,
        connect_args={"connect_timeout": connect_timeout, "prepare_threshold": None},
    )
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1 FROM v_season_summary LIMIT 1"))
    finally:
        engine.dispose()


def run(settings: Settings, role: str = ROLE) -> None:
    if settings.readonly_database_url is None:
        raise ReadonlyRoleError("READONLY_DATABASE_URL is not set (see .env.example)")
    readonly_url = settings.readonly_database_url.get_secret_value()
    password = credentials(readonly_url, role)
    admin_engine = create_db_engine(settings)
    try:
        enable_login(admin_engine, password, role)
    finally:
        admin_engine.dispose()
    check_access(readonly_url, settings.database_connect_timeout)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        run(Settings())
    except ReadonlyRoleError as exc:
        logger.error("%s", exc)
        return 1
    except SQLAlchemyError as exc:
        # Class only: driver messages can include connection details.
        logger.error("Database error: %s", type(exc.orig or exc).__name__)
        return 1
    logger.info("%s can log in and read the stats views", ROLE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
