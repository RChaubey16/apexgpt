"""Knowledge retrieval over the narrative corpus (Phase 3).

    from app.retrieval import build_retriever
    retriever = build_retriever(settings)
    results = retriever.retrieve(session, "Senna Prost Suzuka collision")  # top 5

Try it from the command line: `uv run python -m app.retrieval "question"`.
"""

from app.core.config import Settings
from app.retrieval.embedder import FastEmbedQueryEmbedder, QueryEmbedder
from app.retrieval.errors import (
    EmbeddingUnavailableError,
    RerankerUnavailableError,
    SearchError,
)
from app.retrieval.filters import NO_FILTERS, SearchFilters, filters_from_query
from app.retrieval.reranker import FastEmbedReranker, Reranker
from app.retrieval.retriever import KnowledgeRetriever
from app.retrieval.search import HybridSearcher, SearchResult


def build_retriever(settings: Settings, *, rerank: bool = True) -> KnowledgeRetriever:
    """Hybrid search + reranking; both models cached in EMBEDDING_CACHE_DIR and
    limited to ONNX_THREADS threads each."""
    cache, threads = settings.embedding_cache_dir, settings.onnx_threads
    searcher = HybridSearcher(FastEmbedQueryEmbedder(cache, threads))
    reranker = FastEmbedReranker(cache, threads) if rerank else None
    return KnowledgeRetriever(searcher, reranker)


__all__ = [
    "NO_FILTERS",
    "EmbeddingUnavailableError",
    "FastEmbedQueryEmbedder",
    "FastEmbedReranker",
    "HybridSearcher",
    "KnowledgeRetriever",
    "QueryEmbedder",
    "Reranker",
    "RerankerUnavailableError",
    "SearchError",
    "SearchFilters",
    "SearchResult",
    "build_retriever",
    "filters_from_query",
]
