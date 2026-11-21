"""Search quality on the real corpus: the F3.1/F3.2 acceptance tests plus a regression set.

Opt-in (CI has no corpus). Needs a database with the Wikipedia chunks loaded
and the real embedding model; it only reads:

    CORPUS_DATABASE_URL=postgresql://…/apexgpt EMBEDDING_CACHE_DIR=../data/models \\
      uv run pytest -m corpus

Each question names articles that must appear in the top 10 hybrid results
(F3.1) and in the top 5 after reranking (F3.2: what the answer is built from).
The set was used to choose the fusion weights, the reranker and its blend
(docs/PROGRESS.md, F3.1 and F3.2); every question passes both.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import normalise_database_url
from app.retrieval import (
    FastEmbedQueryEmbedder,
    FastEmbedReranker,
    HybridSearcher,
    KnowledgeRetriever,
)
from app.retrieval.retriever import TOP_K

pytestmark = pytest.mark.corpus

_URL = os.environ.get("CORPUS_DATABASE_URL")
if not _URL:
    pytest.skip("CORPUS_DATABASE_URL not set", allow_module_level=True)

TOP = 10

# Phase 2 → F3.1 acceptance criterion (docs/PROGRESS.md).
ACCEPTANCE = (
    "Senna Prost Suzuka collision",
    ["1989 Japanese Grand Prix", "1990 Japanese Grand Prix"],
)
REGRESSION = {
    "Lauda Nurburgring fire 1976": ["1976 German Grand Prix"],
    "Explain Abu Dhabi 2021": ["2021 Abu Dhabi Grand Prix"],
    "How did Hunt beat Lauda in 1976": ["Hunt–Lauda rivalry"],
    "Raikkonen 2007 championship": ["Kimi Räikkönen"],
    "Schumacher Hill collision Adelaide 1994": ["1994 Australian Grand Prix"],
    "Crashgate Piquet Singapore": ["Renault Formula One crash controversy"],
    "Grosjean fire Bahrain": ["2020 Bahrain Grand Prix"],
    "Spygate McLaren Ferrari": ["2007 Formula One espionage controversy"],
    "Multi 21 Vettel Webber": ["2013 Malaysian Grand Prix"],
    "Senna Monaco 1984 rain": ["1984 Monaco Grand Prix"],
    "Schumacher Villeneuve Jerez 1997": ["1997 European Grand Prix"],
    "Indianapolis 2005 tyre fiasco Michelin": ["2005 United States Grand Prix"],
    "Gilles Villeneuve fatal crash Zolder": ["1982 Belgian Grand Prix"],
    "Button wins Canada 2011 in the rain": ["2011 Canadian Grand Prix"],
}


@pytest.fixture(scope="module")
def session() -> Iterator[Session]:
    engine = create_engine(
        normalise_database_url(_URL), connect_args={"prepare_threshold": None}
    )
    with Session(engine) as s:
        yield s
        s.rollback()
    engine.dispose()


@pytest.fixture(scope="module")
def searcher() -> HybridSearcher:
    cache = os.environ.get("EMBEDDING_CACHE_DIR")
    return HybridSearcher(FastEmbedQueryEmbedder(Path(cache) if cache else None))


@pytest.fixture(scope="module")
def retriever(searcher: HybridSearcher) -> KnowledgeRetriever:
    cache = os.environ.get("EMBEDDING_CACHE_DIR")
    return KnowledgeRetriever(
        searcher, FastEmbedReranker(Path(cache) if cache else None)
    )


def top_titles(searcher: HybridSearcher, session: Session, query: str) -> list[str]:
    return [r.title for r in searcher.search(session, query, limit=TOP)]


def reranked_titles(
    retriever: KnowledgeRetriever, session: Session, query: str
) -> list[str]:
    results = retriever.retrieve(session, query)
    assert all(r.rerank_score is not None for r in results), "reranker did not run"
    return [r.title for r in results]


def test_senna_prost_suzuka_returns_both_japanese_grands_prix(
    searcher: HybridSearcher, session: Session
) -> None:
    query, expected = ACCEPTANCE
    titles = top_titles(searcher, session, query)

    missing = [title for title in expected if title not in titles]
    assert not missing, f"{missing} not in the top {TOP}: {titles}"


@pytest.mark.parametrize(
    ("query", "expected"), REGRESSION.items(), ids=list(REGRESSION)
)
def test_expected_article_in_top_results(
    searcher: HybridSearcher, session: Session, query: str, expected: list[str]
) -> None:
    titles = top_titles(searcher, session, query)

    missing = [title for title in expected if title not in titles]
    assert not missing, f"{missing} not in the top {TOP}: {titles}"


# --- F3.2: after reranking, the top 5 ---


def test_senna_prost_suzuka_holds_in_the_reranked_top_5(
    retriever: KnowledgeRetriever, session: Session
) -> None:
    query, expected = ACCEPTANCE
    titles = reranked_titles(retriever, session, query)

    missing = [title for title in expected if title not in titles]
    assert not missing, f"{missing} not in the reranked top {TOP_K}: {titles}"


@pytest.mark.parametrize(
    ("query", "expected"), REGRESSION.items(), ids=list(REGRESSION)
)
def test_expected_article_in_reranked_top_5(
    retriever: KnowledgeRetriever, session: Session, query: str, expected: list[str]
) -> None:
    titles = reranked_titles(retriever, session, query)

    missing = [title for title in expected if title not in titles]
    assert not missing, f"{missing} not in the reranked top {TOP_K}: {titles}"
