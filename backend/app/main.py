"""FastAPI application factory.

Run with: uvicorn app.main:create_app --factory
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import sessionmaker

from app import __version__
from app.answer import build_orchestrator
from app.api.routes import chat, favicon, feedback, health
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.rate_limit import RateLimiter, parse_limits
from app.db.session import create_db_engine


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(
        settings.log_level,
        log_file=settings.log_file,
        max_bytes=settings.log_file_max_mb * 1024 * 1024,
        backups=settings.log_file_backups,
    )

    engine = create_db_engine(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        app.state.orchestrator.close()
        engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        lifespan=lifespan,
        # Interactive API docs only outside production.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.state.engine = engine
    app.state.session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    # Built once and shared: models, connections and the entity index load on
    # first use, so startup stays fast and works without the database.
    app.state.orchestrator = build_orchestrator(settings, app.state.session_factory)
    app.state.rate_limiter = RateLimiter(
        {
            "chat": parse_limits(settings.rate_limit_chat),
            "feedback": parse_limits(settings.rate_limit_feedback),
        }
    )
    app.dependency_overrides[get_settings] = lambda: settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        # So the browser can read when to retry after a 429.
        expose_headers=["Retry-After"],
    )
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(feedback.router)
    app.include_router(favicon.router)
    return app
