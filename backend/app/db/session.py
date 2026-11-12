"""Database engine, sessions and connectivity checks.

The engine is created once per app (stored on `app.state`) and connects lazily,
so the API starts even when the database is unreachable or suspended.
"""

import logging
from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings

logger = logging.getLogger(__name__)


def create_db_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.database_url.get_secret_value(),
        # Neon suspends idle computes and drops connections: test before use.
        pool_pre_ping=True,
        pool_recycle=300,
        # Small pool: single uvicorn worker, low traffic, free-tier limits.
        pool_size=5,
        max_overflow=5,
        pool_timeout=10,
        connect_args={
            "connect_timeout": settings.database_connect_timeout,
            "application_name": "apexgpt-backend",
            # Disable server-side prepared statements: safe behind Neon's
            # PgBouncer pooler (transaction mode).
            "prepare_threshold": None,
        },
        # Never echo SQL: queries may contain user input.
        echo=False,
    )


def check_database(engine: Engine) -> bool:
    """Return True if a trivial query succeeds. Never raises."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        # Log the error class only: driver messages can include host details.
        logger.warning("Database check failed: %s", type(exc).__name__)
        return False
    return True


def get_engine(request: Request) -> Engine:
    return request.app.state.engine


def get_session(request: Request) -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    factory: sessionmaker[Session] = request.app.state.session_factory
    with factory() as session:
        yield session
