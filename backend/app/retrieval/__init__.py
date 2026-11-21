"""Knowledge retrieval over the narrative corpus (Phase 3).

    from app.retrieval import FastEmbedQueryEmbedder, HybridSearcher
    searcher = HybridSearcher(FastEmbedQueryEmbedder(settings.embedding_cache_dir))
    results = searcher.search(session, "Senna Prost Suzuka collision")

Try it from the command line: `uv run python -m app.retrieval "question"`.
"""

from app.retrieval.embedder import FastEmbedQueryEmbedder, QueryEmbedder
from app.retrieval.errors import EmbeddingUnavailableError, SearchError
from app.retrieval.filters import NO_FILTERS, SearchFilters, filters_from_query
from app.retrieval.search import HybridSearcher, SearchResult

__all__ = [
    "NO_FILTERS",
    "EmbeddingUnavailableError",
    "FastEmbedQueryEmbedder",
    "HybridSearcher",
    "QueryEmbedder",
    "SearchError",
    "SearchFilters",
    "SearchResult",
    "filters_from_query",
]
