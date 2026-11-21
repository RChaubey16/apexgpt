"""Unit tests for HybridSearcher: input validation, wiring and errors (no database).

The SQL itself is tested against Postgres in tests/integration/test_hybrid_search.py.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError

from app.retrieval.embedder import DIMENSIONS
from app.retrieval.errors import EmbeddingUnavailableError, SearchError
from app.retrieval.filters import NO_FILTERS, SearchFilters
from app.retrieval.search import (
    CANDIDATES,
    MAX_LIMIT,
    MAX_QUERY_CHARS,
    HybridSearcher,
    normalise_query,
)


class FakeEmbedder:
    def __init__(self, vector: list[float] | None = None) -> None:
        self.vector = vector or [0.1] * DIMENSIONS
        self.queries: list[str] = []

    def embed_query(self, query: str) -> list[float]:
        self.queries.append(query)
        return self.vector


def candidate(source: str, rank: int, pageid: int, chunk_index: int) -> Any:
    return SimpleNamespace(
        source=source, rank=rank, pageid=pageid, chunk_index=chunk_index
    )


def chunk_row(pageid: int, chunk_index: int, **extra: object) -> Any:
    values = {
        "pageid": pageid,
        "chunk_index": chunk_index,
        "title": f"Article {pageid}",
        "section": None,
        "text": f"Text {pageid}.{chunk_index}",
        "source_url": f"https://en.wikipedia.org/?curid={pageid}",
        "season": None,
        "race_id": None,
    } | extra
    return SimpleNamespace(**values)


class FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class FakeSession:
    """Answers the searcher's three statements in order: settings, candidates, rows."""

    def __init__(self, candidates: list[Any], rows: list[Any]) -> None:
        self._answers = [[], candidates, rows]
        self.calls: list[tuple[str, dict]] = []

    def execute(self, statement: Any, params: dict | None = None) -> FakeResult:
        self.calls.append((str(statement), params or {}))
        return FakeResult(self._answers[len(self.calls) - 1])


class FailingSession:
    def execute(self, statement: Any, params: dict | None = None) -> FakeResult:
        raise OperationalError(
            "SELECT", {}, Exception("could not connect to db.internal:5432 password=x")
        )


def test_results_follow_the_fused_order_with_their_metadata() -> None:
    session = FakeSession(
        candidates=[
            candidate("vector", 1, 10, 0),
            candidate("vector", 2, 20, 3),
            candidate("text", 1, 20, 3),
            candidate("article", 1, 30, 1),
        ],
        rows=[  # any order from the database
            chunk_row(30, 1),
            chunk_row(10, 0, season=1989, race_id=7, section="Race"),
            chunk_row(20, 3),
        ],
    )

    results = HybridSearcher(FakeEmbedder()).search(session, "Senna Suzuka")  # type: ignore[arg-type]

    assert [(r.pageid, r.chunk_index) for r in results] == [(20, 3), (10, 0), (30, 1)]
    assert results[0].signals == ("vector", "text")
    assert results[1].section == "Race"
    assert (results[1].season, results[1].race_id) == (1989, 7)
    assert results[0].score > results[1].score > results[2].score


def test_parameters_sent_to_the_database() -> None:
    embedder = FakeEmbedder([0.25] * DIMENSIONS)
    session = FakeSession([candidate("vector", 1, 10, 0)], [chunk_row(10, 0)])

    HybridSearcher(embedder).search(session, "  Hunt   beat Lauda in 1976 ")  # type: ignore[arg-type]

    settings_sql, settings = session.calls[0]
    assert "hnsw.ef_search" in settings_sql and "relaxed_order" in settings_sql
    assert int(settings["ef"]) >= CANDIDATES  # HNSW must examine enough rows
    _, params = session.calls[1]
    assert params["query"] == "Hunt beat Lauda in 1976"  # whitespace collapsed
    assert params["seasons"] == [1976]  # extracted from the question
    assert params["n"] == CANDIDATES
    assert params["vector"] == "[" + ",".join(["0.25"] * DIMENSIONS) + "]"
    assert embedder.queries == ["Hunt beat Lauda in 1976"]
    _, keys = session.calls[2]
    assert (keys["pageids"], keys["indexes"]) == ([10], [0])


def test_explicit_filters_replace_the_extracted_ones() -> None:
    session = FakeSession([], [])
    searcher = HybridSearcher(FakeEmbedder())

    searcher.search(session, "Lauda 1976", filters=NO_FILTERS)  # type: ignore[arg-type]
    assert session.calls[1][1]["seasons"] is None

    session = FakeSession([], [])
    searcher.search(session, "Lauda", filters=SearchFilters(seasons=(1977,)))  # type: ignore[arg-type]
    assert session.calls[1][1]["seasons"] == [1977]


def test_no_candidates_means_no_results_and_no_row_query() -> None:
    session = FakeSession([], [])

    assert HybridSearcher(FakeEmbedder()).search(session, "zzz") == []  # type: ignore[arg-type]
    assert len(session.calls) == 2


def test_rows_deleted_meanwhile_are_skipped() -> None:
    session = FakeSession(
        [candidate("vector", 1, 10, 0), candidate("vector", 2, 20, 0)],
        [chunk_row(20, 0)],  # (10, 0) was removed by a concurrent sync
    )

    results = HybridSearcher(FakeEmbedder()).search(session, "q")  # type: ignore[arg-type]

    assert [(r.pageid, r.chunk_index) for r in results] == [(20, 0)]


def test_limit_is_applied() -> None:
    session = FakeSession(
        [candidate("vector", i, i, 0) for i in range(1, 8)],
        [chunk_row(i, 0) for i in range(1, 8)],
    )

    results = HybridSearcher(FakeEmbedder()).search(session, "q", limit=3)  # type: ignore[arg-type]

    assert [r.pageid for r in results] == [1, 2, 3]


@pytest.mark.parametrize("limit", [0, -1, MAX_LIMIT + 1])
def test_invalid_limit_is_rejected_before_any_work(limit: int) -> None:
    embedder = FakeEmbedder()

    with pytest.raises(ValueError, match="limit"):
        HybridSearcher(embedder).search(FailingSession(), "q", limit=limit)  # type: ignore[arg-type]
    assert embedder.queries == []


def test_database_errors_become_a_safe_search_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with pytest.raises(SearchError, match="unavailable") as info:
        HybridSearcher(FakeEmbedder()).search(FailingSession(), "q")  # type: ignore[arg-type]

    assert info.value.__cause__ is None
    assert "db.internal" not in str(info.value) and "password" not in caplog.text
    assert "OperationalError" in caplog.text


def test_embedder_errors_propagate() -> None:
    class Broken:
        def embed_query(self, query: str) -> list[float]:
            raise EmbeddingUnavailableError("The search model could not be loaded")

    with pytest.raises(EmbeddingUnavailableError):
        HybridSearcher(Broken()).search(FakeSession([], []), "q")  # type: ignore[arg-type]


def test_invalid_vectors_from_the_embedder_are_rejected() -> None:
    embedder = FakeEmbedder([0.1] * 10)

    with pytest.raises(EmbeddingUnavailableError, match="invalid vector"):
        HybridSearcher(embedder).search(FakeSession([], []), "q")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("  Senna\n\tProst  ", "Senna Prost"),
        ("Nürburgring\x00 1976", "Nürburgring 1976"),  # NUL would break the driver
        ("a" * MAX_QUERY_CHARS, "a" * MAX_QUERY_CHARS),
    ],
)
def test_queries_are_normalised(raw: str, clean: str) -> None:
    assert normalise_query(raw) == clean


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("", "empty"),
        (" \n\t ", "empty"),
        ("\x00\x01", "empty"),
        ("a" * (MAX_QUERY_CHARS + 1), "at most"),
        (None, "string"),
    ],
)
def test_bad_queries_are_rejected(raw: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        normalise_query(raw)  # type: ignore[arg-type]
