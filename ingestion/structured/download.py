"""Download the Jolpica-F1 CSV database dump, verify it and cache it in data/.

Jolpica's free tier serves dumps delayed by 14 days, for non-commercial use,
without authentication: https://github.com/jolpica/jolpica-f1/blob/main/docs/database_dumps.md

The dump index publishes each file's SHA-256 and size; a download is only
accepted (and cached) if both match, so a cached file is always a verified one.
"""

import hashlib
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import IO, Literal

from pydantic import BaseModel, Field, HttpUrl, ValidationError, field_validator

from common.http import Opener, open_url
from structured.errors import DownloadError

logger = logging.getLogger(__name__)

DUMPS_INDEX_URL = "https://api.jolpi.ca/data/dumps/download/"
# Generic client name: no project or personal details in requests to third parties.
USER_AGENT = "f1-dump-loader/0.1"
TIMEOUT_SECONDS = 60
MAX_INDEX_BYTES = 1_000_000
# The CSV dump is ~15 MB; refuse anything wildly larger.
MAX_DUMP_BYTES = 200_000_000
MAX_ATTEMPTS = 3
CHUNK_BYTES = 1 << 16


class DumpInfo(BaseModel):
    dump_type: Literal["csv", "sql"]
    file_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    file_size: int = Field(gt=0, le=MAX_DUMP_BYTES)
    uploaded_at: str
    download_url: HttpUrl

    @field_validator("download_url")
    @classmethod
    def _https_only(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https":
            raise ValueError("download_url must use https")
        return value


class DumpIndex(BaseModel):
    delay_days: int
    delayed_dumps: dict[str, DumpInfo]


def _open(url: str, opener: Opener) -> IO[bytes]:
    return open_url(
        url,
        opener,
        user_agent=USER_AGENT,
        error=DownloadError,
        timeout=TIMEOUT_SECONDS,
        attempts=MAX_ATTEMPTS,
    )


def fetch_dump_info(opener: Opener = urllib.request.urlopen) -> DumpInfo:
    """Return the latest free (delayed) CSV dump listed in the dump index."""
    with _open(DUMPS_INDEX_URL, opener) as response:
        body = response.read(MAX_INDEX_BYTES + 1)
    if len(body) > MAX_INDEX_BYTES:
        raise DownloadError("dump index response is unexpectedly large")
    try:
        index = DumpIndex.model_validate(json.loads(body))
    except (ValueError, ValidationError) as exc:
        raise DownloadError(f"dump index has an unexpected format: {exc}") from None
    info = index.delayed_dumps.get("csv")
    if info is None:
        raise DownloadError("dump index lists no CSV dump")
    return info


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def cached_dump_path(cache_dir: Path, info: DumpInfo) -> Path:
    return cache_dir / f"jolpica-csv-{info.file_hash[:16]}.zip"


def download_dump(
    info: DumpInfo, cache_dir: Path, opener: Opener = urllib.request.urlopen
) -> Path:
    """Return a verified local copy of the dump, downloading it if not cached."""
    target = cached_dump_path(cache_dir, info)
    if target.exists():
        if sha256_of(target) == info.file_hash:
            logger.info("Using cached dump %s", target.name)
            return target
        logger.warning(
            "Cached dump %s failed verification; downloading again", target.name
        )
        target.unlink()

    cache_dir.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    digest = hashlib.sha256()
    size = 0
    logger.info("Downloading %s dump (%.1f MB)", info.uploaded_at, info.file_size / 1e6)
    try:
        with _open(str(info.download_url), opener) as response, partial.open(
            "wb"
        ) as out:
            while chunk := response.read(CHUNK_BYTES):
                size += len(chunk)
                if size > info.file_size:
                    raise DownloadError("dump is larger than the index says")
                digest.update(chunk)
                out.write(chunk)
        if size != info.file_size:
            raise DownloadError(
                f"dump size {size} does not match the index ({info.file_size})"
            )
        if digest.hexdigest() != info.file_hash:
            raise DownloadError("dump SHA-256 does not match the index")
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return target
