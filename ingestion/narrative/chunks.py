"""Retrieval chunks on disk (data/narrative/chunks.jsonl), for the embedder.

One JSON object per line: the chunk text and its section, the source page
(title, page id, revision, URL for CC BY-SA attribution) and the article's
links to the structured data (season, race_id, circuit_id, driver_ids,
constructor_ids, topic), so retrieval can filter by them.
"""

from collections.abc import Iterable, Iterator
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from narrative.articles import ArticleRecord
from narrative.chunker import HEADING_SEPARATOR, chunk_sections
from narrative.jsonl import read_jsonl, write_jsonl
from narrative.selection import Depth, Kind


def chunks_path(data_dir: Path) -> Path:
    return data_dir / "narrative" / "chunks.jsonl"


class ChunkRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pageid: int
    index: int = Field(ge=0)  # position in the article; (pageid, index) is unique
    title: str
    revid: int
    source_url: str
    section: tuple[str, ...]  # heading path; () is the lead
    text: str = Field(min_length=1)
    tokens: int = Field(gt=0)  # estimated, including the heading
    depth: Depth
    kinds: tuple[Kind, ...]
    season: int | None = None
    race_id: int | None = None
    circuit_id: int | None = None
    driver_ids: tuple[int, ...] = ()
    constructor_ids: tuple[int, ...] = ()
    topic: str | None = None

    @property
    def heading(self) -> str:
        """Where the text is from, e.g. "1990 Japanese Grand Prix > Race"."""
        return HEADING_SEPARATOR.join((self.title, *self.section))

    @property
    def embedding_text(self) -> str:
        return f"{self.heading}\n\n{self.text}"


def chunk_article(article: ArticleRecord) -> list[ChunkRecord]:
    chunks = chunk_sections(article.title, [(s.path, s.text) for s in article.sections])
    return [
        ChunkRecord(
            pageid=article.pageid,
            index=index,
            title=article.title,
            revid=article.revid,
            source_url=article.url,
            section=chunk.path,
            text=chunk.text,
            tokens=chunk.tokens,
            depth=article.depth,
            kinds=article.kinds,
            season=article.season,
            race_id=article.race_id,
            circuit_id=article.circuit_id,
            driver_ids=article.driver_ids,
            constructor_ids=article.constructor_ids,
            topic=article.topic,
        )
        for index, chunk in enumerate(chunks)
    ]


def write_chunks(path: Path, records: Iterable[ChunkRecord]) -> int:
    return write_jsonl(path, records)


def read_chunks(path: Path) -> Iterator[ChunkRecord]:
    return read_jsonl(path, ChunkRecord, "python -m narrative.chunk")
