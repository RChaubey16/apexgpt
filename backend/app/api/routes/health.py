"""Health endpoints.

- `/health`: liveness only. Used by the Docker/Coolify healthcheck every 30s,
  so it must NOT touch the database: polling Neon would stop it from ever
  auto-suspending and burn the free tier's compute hours.
- `/health/ready`: readiness, including a database check. Called by the
  frontend on page load, which also wakes a suspended Neon compute.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import Engine

from app import __version__
from app.core.config import Environment, Settings, get_settings
from app.db.session import check_database, get_engine

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str
    environment: Environment


class ReadinessResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    database: Literal["ok", "unavailable"]


@router.get("/health", response_model=HealthResponse)
def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="apexgpt-backend",
        version=__version__,
        environment=settings.environment,
    )


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
)
def readiness(
    engine: Annotated[Engine, Depends(get_engine)], response: Response
) -> ReadinessResponse:
    if check_database(engine):
        return ReadinessResponse(status="ok", database="ok")
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="unavailable", database="unavailable")
