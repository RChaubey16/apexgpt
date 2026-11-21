import pytest

from app.retrieval import build_retriever
from app.retrieval.errors import RerankerUnavailableError, SearchError
from app.retrieval.filters import NO_FILTERS, SearchFilters
from app.retrieval.fusion import RRF_K
from app.retrieval.reranker import FastEmbedReranker
from app.retrieval.retriever import (
    CANDIDATES,
    HYBRID_WEIGHT,
    RERANK_WEIGHT,
    TOP_K,
    KnowledgeRetriever,
    blend,
    document_text,
)
from app.retrieval.search import SearchResult
from tests.conftest import make_settings


def result(
    pageid: int, chunk_index: int = 0, section: str | None = None
) -> SearchResult:
    return SearchResult(
        pageid=pageid,
        chunk_index=chunk_index,
        title=f"Article {pageid}",
        section=section,
        text=f"Text {pageid}.{chunk_index}",
        source_url=f"https://en.wikipedia.org/?curid={pageid}",
        season=None,
        race_id=None,
        score=0.01,
        signals=("vector",),
    )


def pageids(results: list[SearchResult]) -> list[int]:
    return [r.pageid for r in results]


class FakeSearcher:
    def __init__(self, candidates: list[SearchResult] | Exception) -> None:
        self.candidates = candidates
        self.calls: list[dict] = []

    def search(self, session, query, *, filters=None, limit=10):
        self.calls.append({"query": query, "filters": filters, "limit": limit})
        if isinstance(self.candidates, Exception):
            raise self.candidates
        return self.candidates[:limit]


class FakeReranker:
    def __init__(self, scores: list[float] | Exception) -> None:
        self.scores = scores
        self.calls: list[tuple[str, list[str]]] = []

    def score(self, query, documents):
        self.calls.append((query, list(documents)))
        if isinstance(self.scores, Exception):
            raise self.scores
        return self.scores


# --- blend ---


def test_blend_weights_the_reranker_twice_as_much() -> None:
    candidates = [result(1), result(2), result(3)]
    # The reranker reverses the hybrid order.
    blended = blend(candidates, [0.1, 0.5, 0.9], top_k=3)

    assert pageids(blended) == [3, 2, 1]
    assert blended[0].score == pytest.approx(
        HYBRID_WEIGHT / (RRF_K + 3) + RERANK_WEIGHT / (RRF_K + 1)
    )


def test_blend_moves_results_by_the_reranker_but_not_far() -> None:
    candidates = [result(i) for i in range(1, 21)]
    scores = [float(20 - i) for i in range(20)]  # the reranker agrees with hybrid...
    scores[0], scores[2] = scores[2], scores[0]  # ...except #1 and #3 swap

    blended = blend(candidates, scores, top_k=5)

    # 3: 1/63 + 2/61 = .04866 · 2: 1/62 + 2/62 = .04839 · 1: 1/61 + 2/63 = .04814
    assert pageids(blended) == [3, 2, 1, 4, 5]


def test_blend_sets_scores_and_keeps_everything_else() -> None:
    original = result(7, 2, section="Race > Race report")

    (blended,) = blend([original], [4.25], top_k=5)

    assert blended.rerank_score == 4.25
    assert blended.score == pytest.approx(
        HYBRID_WEIGHT / (RRF_K + 1) + RERANK_WEIGHT / (RRF_K + 1)
    )
    assert (blended.pageid, blended.chunk_index, blended.section) == (
        7,
        2,
        "Race > Race report",
    )
    assert blended.signals == original.signals and blended.text == original.text
    assert original.rerank_score is None  # the input is not modified


def test_blend_ties_keep_the_hybrid_order() -> None:
    candidates = [result(1), result(2), result(3)]

    assert pageids(blend(candidates, [1.0, 1.0, 1.0], top_k=3)) == [1, 2, 3]


def test_blend_returns_top_k() -> None:
    candidates = [result(i) for i in range(1, 11)]

    assert len(blend(candidates, [0.0] * 10, top_k=4)) == 4


def test_blend_needs_one_score_per_candidate() -> None:
    with pytest.raises(ValueError, match="one score per candidate"):
        blend([result(1), result(2)], [1.0], top_k=2)


def test_blend_of_nothing_is_nothing() -> None:
    assert blend([], [], top_k=5) == []


def test_document_text_is_heading_then_text() -> None:
    assert document_text(result(1)) == "Article 1\nText 1.0"
    assert (
        document_text(result(1, 3, section="Race > Post-race"))
        == "Article 1 > Race > Post-race\nText 1.3"
    )


# --- KnowledgeRetriever ---


def test_retrieves_candidates_reranks_and_keeps_the_top_5() -> None:
    candidates = [result(i) for i in range(1, CANDIDATES + 1)]
    # The reranker reverses the hybrid order: the last candidate is the best.
    # (Reranked #1 alone can't lift hybrid #20 past hybrid #1-#5 when the
    # reranker otherwise agrees with them; see test_blend_*.)
    scores = [float(i) for i in range(CANDIDATES)]
    searcher, reranker = FakeSearcher(candidates), FakeReranker(scores)

    results = KnowledgeRetriever(searcher, reranker).retrieve(  # type: ignore[arg-type]
        None, "  Senna   Suzuka "  # type: ignore[arg-type]
    )

    assert len(results) == TOP_K == 5
    assert results[0].pageid == CANDIDATES
    assert searcher.calls == [
        {"query": "Senna Suzuka", "filters": None, "limit": CANDIDATES}
    ]
    query, documents = reranker.calls[0]
    assert query == "Senna Suzuka"  # normalised before reranking too
    assert documents == [document_text(c) for c in candidates]


def test_filters_and_top_k_are_passed_through() -> None:
    searcher = FakeSearcher([result(i) for i in range(1, 9)])
    retriever = KnowledgeRetriever(searcher, FakeReranker([0.0] * 8))  # type: ignore[arg-type]

    results = retriever.retrieve(
        None, "q", filters=SearchFilters(seasons=(1976,)), top_k=3  # type: ignore[arg-type]
    )
    retriever.retrieve(None, "q", filters=NO_FILTERS)  # type: ignore[arg-type]

    assert len(results) == 3
    assert searcher.calls[0]["filters"] == SearchFilters(seasons=(1976,))
    assert searcher.calls[1]["filters"] == NO_FILTERS


def test_without_a_reranker_the_hybrid_order_is_kept() -> None:
    candidates = [result(i) for i in range(1, 9)]

    results = KnowledgeRetriever(FakeSearcher(candidates), None).retrieve(  # type: ignore[arg-type]
        None, "q"  # type: ignore[arg-type]
    )

    assert pageids(results) == [1, 2, 3, 4, 5]
    assert all(r.rerank_score is None for r in results)


def test_a_failing_reranker_falls_back_to_the_hybrid_order(
    caplog: pytest.LogCaptureFixture,
) -> None:
    candidates = [result(i) for i in range(1, 9)]
    reranker = FakeReranker(RerankerUnavailableError("could not be loaded"))

    results = KnowledgeRetriever(FakeSearcher(candidates), reranker).retrieve(  # type: ignore[arg-type]
        None, "q"  # type: ignore[arg-type]
    )

    assert pageids(results) == [1, 2, 3, 4, 5]
    assert all(r.rerank_score is None for r in results)
    assert "Reranker unavailable; using the hybrid order" in caplog.text


def test_no_candidates_means_no_reranking() -> None:
    reranker = FakeReranker([])

    assert KnowledgeRetriever(FakeSearcher([]), reranker).retrieve(None, "q") == []  # type: ignore[arg-type]
    assert reranker.calls == []


def test_search_errors_propagate() -> None:
    searcher = FakeSearcher(SearchError("Knowledge search is unavailable right now"))

    with pytest.raises(SearchError, match="unavailable"):
        KnowledgeRetriever(searcher, FakeReranker([])).retrieve(None, "q")  # type: ignore[arg-type]


@pytest.mark.parametrize("top_k", [0, CANDIDATES + 1])
def test_invalid_top_k_is_rejected_before_searching(top_k: int) -> None:
    searcher = FakeSearcher([])

    with pytest.raises(ValueError, match="top_k"):
        KnowledgeRetriever(searcher, None).retrieve(None, "q", top_k=top_k)  # type: ignore[arg-type]
    assert searcher.calls == []


def test_empty_query_is_rejected_before_searching() -> None:
    searcher = FakeSearcher([])

    with pytest.raises(ValueError, match="empty"):
        KnowledgeRetriever(searcher, None).retrieve(None, "   ")  # type: ignore[arg-type]
    assert searcher.calls == []


def test_build_retriever_wires_both_models(tmp_path) -> None:
    settings = make_settings(embedding_cache_dir=str(tmp_path), onnx_threads=2)

    with_rerank = build_retriever(settings)
    without = build_retriever(settings, rerank=False)

    assert isinstance(with_rerank._reranker, FastEmbedReranker)
    assert with_rerank._reranker._cache_dir == tmp_path
    assert with_rerank._searcher._embedder._cache_dir == tmp_path
    assert with_rerank._reranker._threads == 2
    assert with_rerank._searcher._embedder._threads == 2
    assert without._reranker is None
