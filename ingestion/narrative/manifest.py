"""The resolved article selection on disk (data/narrative/selection.json).

Written by `python -m narrative.select`; read by the fetcher (and later by the
cleaner and chunker, which need each article's depth and metadata). Written
atomically, so an interrupted run keeps the previous manifest.
"""

import json
import os
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from narrative.errors import SelectionError
from narrative.selection import Selected, summarise

MANIFEST_VERSION = 1
MAX_MANIFEST_BYTES = 50_000_000


def manifest_path(data_dir: Path) -> Path:
    return data_dir / "narrative" / "selection.json"


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int
    generated_at: datetime
    counts: dict[str, dict[str, int]]
    articles: tuple[Selected, ...]


def write_manifest(path: Path, articles: Sequence[Selected]) -> Manifest:
    missing_pages = [a.title for a in articles if a.pageid is None]
    if missing_pages:
        raise SelectionError(
            f"refusing to write unresolved articles to the manifest: {missing_pages[:3]}"
        )
    manifest = Manifest(
        version=MANIFEST_VERSION,
        generated_at=datetime.now(UTC),
        counts=summarise(articles),
        articles=tuple(articles),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(manifest.model_dump_json(indent=1, exclude_defaults=True))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return manifest


def read_manifest(path: Path) -> Manifest:
    if not path.is_file():
        raise SelectionError(
            f"no article selection at {path}; run `python -m narrative.select` first"
        )
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise SelectionError(f"{path.name} is unexpectedly large")
    try:
        manifest = Manifest.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError):
        raise SelectionError(
            f"{path.name} is unreadable; run `python -m narrative.select` again"
        ) from None
    if manifest.version != MANIFEST_VERSION:
        raise SelectionError(
            f"{path.name} has version {manifest.version} (expected {MANIFEST_VERSION}); "
            "run `python -m narrative.select` again"
        )
    titles = [a.title for a in manifest.articles]
    pageids = [a.pageid for a in manifest.articles]
    if (
        None in pageids
        or len(set(titles)) != len(titles)
        or len(set(pageids)) != len(pageids)
    ):
        raise SelectionError(
            f"{path.name} has unresolved or duplicate articles; "
            "run `python -m narrative.select` again"
        )
    return manifest
