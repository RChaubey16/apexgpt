"""Cleaned articles on disk (data/narrative/articles.jsonl), for the chunker.

One JSON object per line: the selection metadata (depth, kinds, season,
race_id, circuit_id, driver_ids, constructor_ids, topic), the source page
(title, page id, revision, URL for CC BY-SA attribution) and the kept sections.
Written atomically, so an interrupted run keeps the previous file.
"""

from collections.abc import Iterable, Iterator
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from narrative.jsonl import read_jsonl, write_jsonl
from narrative.selection import Depth, Kind


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
    return write_jsonl(path, records)


def read_articles(path: Path) -> Iterator[ArticleRecord]:
    return read_jsonl(path, ArticleRecord, "python -m narrative.clean")
