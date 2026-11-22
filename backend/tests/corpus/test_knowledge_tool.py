"""search_f1_knowledge on the real corpus (F3.6): the sources a question gets.

Opt-in and read-only, like the other corpus tests:

    CORPUS_DATABASE_URL=postgresql://…/apexgpt EMBEDDING_CACHE_DIR=../data/models \\
      uv run pytest -m corpus
"""

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import normalise_database_url
from app.retrieval import FastEmbedQueryEmbedder, FastEmbedReranker, HybridSearcher
from app.retrieval.retriever import KnowledgeRetriever
from app.tools.knowledge import KnowledgeTool

pytestmark = pytest.mark.corpus

_URL = os.environ.get("CORPUS_DATABASE_URL")
if not _URL:
    pytest.skip("CORPUS_DATABASE_URL not set", allow_module_level=True)

CASES = {
    "acceptance": (
        {"query": "Senna Prost Suzuka collision"},
        {"1989 Japanese Grand Prix", "1990 Japanese Grand Prix"},
    ),
    "abu dhabi 2021": (
        {"query": "Abu Dhabi 2021 safety car controversy"},
        {"2021 Abu Dhabi Grand Prix"},
    ),
    "season filter": (
        {"query": "Lauda Nurburgring fire", "seasons": [1976]},
        {"1976 German Grand Prix"},
    ),
    "title decider": (
        {"query": "Hunt Lauda 1976 championship"},
        {"1976 Japanese Grand Prix"},
    ),
}


@pytest.fixture(scope="module")
def tool() -> Iterator[KnowledgeTool]:
    engine = create_engine(
        normalise_database_url(_URL), connect_args={"prepare_threshold": None}
    )
    cache = os.environ.get("EMBEDDING_CACHE_DIR")
    cache_dir = Path(cache) if cache else None
    retriever = KnowledgeRetriever(
        HybridSearcher(FastEmbedQueryEmbedder(cache_dir)), FastEmbedReranker(cache_dir)
    )
    yield KnowledgeTool(retriever, sessionmaker(bind=engine))
    engine.dispose()


@pytest.mark.parametrize(("arguments", "expected"), CASES.values(), ids=list(CASES))
def test_expected_sources(
    tool: KnowledgeTool, arguments: dict, expected: set[str]
) -> None:
    outcome = tool.call(arguments)

    titles = {s.title for s in outcome.sources}
    assert outcome.ok and expected <= titles, titles
    assert [s.id for s in outcome.sources] == ["S1", "S2", "S3", "S4", "S5"]


def test_a_payload_fits_the_token_budget(tool: KnowledgeTool) -> None:
    outcome = tool.call({"query": "Senna Prost Suzuka collision"})

    assert len(json.dumps(outcome.payload, ensure_ascii=False)) < 12_000  # ~3k tokens
