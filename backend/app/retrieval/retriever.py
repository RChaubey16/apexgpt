"""Knowledge retrieval: hybrid search, then reranking, then the top 5 (F3.2).

1. HybridSearcher returns 10 candidates (vector + full-text + article lists).
2. The cross-encoder scores each candidate against the question.
3. The reranker's order is blended with the hybrid order by Reciprocal Rank
   Fusion, with the reranker weighted ×2, and the best 5 are kept.

Blending rather than replacing keeps what the hybrid lists know (every word
matched, article-level matches) when the small cross-encoder is unsure. On the
labelled questions, blending put all 15 expected articles in the top 5 and the
reranker alone put 14. 10, 12, 15, 20 and 30 candidates gave identical results:
under the blend a low hybrid rank can't reach the top 5 on the reranker alone.
Reranking costs ~70 ms per candidate on one CPU, so 10 halves it against 20
(docs/archive/v1.0.0-mvp/PROGRESS.md, F3.2).

If the reranker fails, the hybrid order is used (logged as a warning), so a
model problem degrades answers instead of failing them.
"""

import dataclasses
import logging
from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.retrieval.errors import RerankerUnavailableError
from app.retrieval.filters import SearchFilters
from app.retrieval.fusion import Ranking, reciprocal_rank_fusion
from app.retrieval.reranker import Reranker
from app.retrieval.search import HybridSearcher, SearchResult, normalise_query

logger = logging.getLogger(__name__)

CANDIDATES = 10
TOP_K = 5
HYBRID_WEIGHT = 1.0
RERANK_WEIGHT = 2.0


def document_text(result: SearchResult) -> str:
    """What the cross-encoder reads: the heading path, then the chunk."""
    return f"{result.heading}\n{result.text}"


def blend(
    candidates: Sequence[SearchResult], scores: Sequence[float], top_k: int
) -> list[SearchResult]:
    """Blend the hybrid order (candidates' order) with the reranker's scores."""
    if len(scores) != len(candidates):
        raise ValueError("one score per candidate is required")
    if not candidates:
        return []
    keys = [(r.pageid, r.chunk_index) for r in candidates]
    # Highest score first; equal scores keep the hybrid order.
    by_score = sorted(range(len(candidates)), key=lambda i: (-scores[i], i))
    fused = reciprocal_rank_fusion(
        [
            Ranking("hybrid", keys, HYBRID_WEIGHT),
            Ranking("rerank", [keys[i] for i in by_score], RERANK_WEIGHT),
        ],
        limit=top_k,
        per_article=None,  # the candidates are already capped per article
    )
    position = {key: i for i, key in enumerate(keys)}
    return [
        dataclasses.replace(
            candidates[position[item.key]],
            score=item.score,
            rerank_score=scores[position[item.key]],
        )
        for item in fused
    ]


class KnowledgeRetriever:
    def __init__(self, searcher: HybridSearcher, reranker: Reranker | None) -> None:
        """reranker=None returns the hybrid order (used by the CLI's --no-rerank)."""
        self._searcher = searcher
        self._reranker = reranker

    def retrieve(
        self,
        session: Session,
        query: str,
        *,
        filters: SearchFilters | None = None,
        top_k: int = TOP_K,
    ) -> list[SearchResult]:
        """The `top_k` most relevant chunks for `query`, best first.

        filters work as in HybridSearcher.search (None: years in the question).
        Raises ValueError for bad input and SearchError when search itself fails;
        a failing reranker falls back to the hybrid order.
        """
        query = normalise_query(query)
        if not 1 <= top_k <= CANDIDATES:
            raise ValueError(f"top_k must be between 1 and {CANDIDATES}")
        candidates = self._searcher.search(
            session, query, filters=filters, limit=CANDIDATES
        )
        if not candidates or self._reranker is None:
            return candidates[:top_k]
        try:
            scores = self._reranker.score(query, [document_text(r) for r in candidates])
        except RerankerUnavailableError:
            logger.warning("Reranker unavailable; using the hybrid order")
            return candidates[:top_k]
        return blend(candidates, scores, top_k)
