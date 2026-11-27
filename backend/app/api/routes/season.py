"""`GET /api/season/current`: the current season's standings and next race (F8.3).

Live data from the Jolpica-F1 API, cached on the server (see
app/season/service.py). The chat's own data still ends with 2025.

Response 200: `SeasonSnapshot`, i.e.

    {"season": 2026, "round": 21, "total_rounds": 23, "complete": false,
     "drivers": [{"position": 1, "given_name": ..., "team": ..., "points": 402.0,
                  "wins": 9, ...}, ...],
     "constructors": [{"position": 1, "name": "Mercedes", ...}, ...],
     "next_race": {"round": 22, "name": "Qatar Grand Prix", "circuit": {...},
                   "start": "2026-11-29T16:00:00Z",
                   "sessions": [{"kind": "practice_1", "start": ...}, ...]},
     "fetched_at": "...", "stale": false}

Times are UTC; the page shows them in the visitor's time zone. `stale: true`
means Jolpica can't be reached and this is the last data (up to 24 h old).
`next_race` is null between the finale and the next calendar's publication.

Errors: 429 with Retry-After over the per-IP limit (RATE_LIMIT_SEASON); 503
when Jolpica can't be reached and nothing is cached (the message is safe to
show). Browsers may cache a response for a minute.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.rate_limit import rate_limit
from app.season.service import SeasonService, SeasonSnapshot, SeasonUnavailable

router = APIRouter(prefix="/api/season", tags=["season"])

UNAVAILABLE = (
    "The current season's data is unavailable right now; please try again later"
)
BROWSER_CACHE_SECONDS = 60


class ErrorResponse(BaseModel):
    detail: str


def get_season_service(request: Request) -> SeasonService:
    return request.app.state.season_service


@router.get(
    "/current",
    response_model=SeasonSnapshot,
    responses={429: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    dependencies=[Depends(rate_limit("season"))],
)
async def current_season(
    service: Annotated[SeasonService, Depends(get_season_service)],
    response: Response,
) -> SeasonSnapshot | JSONResponse:
    try:
        snapshot = await service.current()
    except SeasonUnavailable:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": UNAVAILABLE},
            headers={"Cache-Control": "no-store"},
        )
    response.headers["Cache-Control"] = f"public, max-age={BROWSER_CACHE_SECONDS}"
    return snapshot
