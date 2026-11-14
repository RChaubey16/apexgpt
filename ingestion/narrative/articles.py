"""Cleaned articles on disk (data/narrative/articles.jsonl), for the chunker.

One JSON object per line: the selection metadata (depth, kinds, season,
race_id, circuit_id, driver_ids, constructor_ids, topic), the source page
(title, page id, revision, URL for CC BY-SA attribution) and the kept sections.
Written atomically, so an interrupted run keeps the previous file.
"""

import json
import os
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from narrative.errors import SelectionError
from narrative.selection import Depth, Kind

MAX_LINE_BYTES = 5_000_000


def articles_path(data_dir: Path) -> Path:
    return data_dir / "narrative" / "articles.jsonl"


class SectionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: tuple[str, ...]  # () is the lead
    text: str = Field(min_length=1)


class ArticleRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str
    pageid: int
    revid: int
    url: str
    depth: Depth
    kinds: tuple[Kind, ...]
    season: int | None = None
    race_id: int | None = None
    circuit_id: int | None = None
    driver_ids: tuple[int, ...] = ()
    constructor_ids: tuple[int, ...] = ()
    topic: str | None = None
    sections: tuple[SectionRecord, ...]

    @property
    def words(self) -> int:
        return sum(len(s.text.split()) for s in self.sections)


def write_articles(path: Path, records: Iterable[ArticleRecord]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".jsonl")
    count = 0
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for record in records:
                f.write(record.model_dump_json(exclude_defaults=True))
                f.write("\n")
                count += 1
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return count


def read_articles(path: Path) -> Iterator[ArticleRecord]:
    if not path.is_file():
        raise SelectionError(
            f"no cleaned articles at {path}; run `python -m narrative.clean` first"
        )
    with path.open(encoding="utf-8") as f:
        for number, line in enumerate(f, start=1):
            if len(line) > MAX_LINE_BYTES:
                raise SelectionError(f"{path.name} line {number} is unexpectedly large")
            try:
                yield ArticleRecord.model_validate(json.loads(line))
            except (ValueError, ValidationError):
                raise SelectionError(
                    f"{path.name} line {number} is unreadable; "
                    "run `python -m narrative.clean` again"
                ) from None
