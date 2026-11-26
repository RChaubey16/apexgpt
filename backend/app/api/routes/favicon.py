"""The API domain's favicon (F8.1).

Browsers ask every site for /favicon.ico, the API domain included (opening
/health/ready in a tab, for example). The file is generated with the
frontend's icons (frontend/scripts/generate-icons.mjs), so both domains show
the same mark. No database, no rate limit, cached for a day.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

FAVICON = Path(__file__).resolve().parents[2] / "static" / "favicon.ico"
CACHE_SECONDS = 86_400

router = APIRouter()


@router.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    if not FAVICON.is_file():
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(
        FAVICON,
        media_type="image/x-icon",
        headers={"Cache-Control": f"public, max-age={CACHE_SECONDS}"},
    )
