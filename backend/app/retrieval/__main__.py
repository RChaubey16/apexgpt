"""Run knowledge retrieval from the command line.

    uv run python -m app.retrieval "Senna Prost Suzuka collision"   # top 5, reranked
    uv run python -m app.retrieval "Lauda 1976" --limit 10 --show-text
    uv run python -m app.retrieval "Lauda 1976" --no-rerank          # hybrid order only
    uv run python -m app.retrieval "Lauda crash" --season 1976 --season 1977
    uv run python -m app.retrieval "Lauda 1976" --no-filters         # ignore the year

Uses DATABASE_URL and EMBEDDING_CACHE_DIR from the environment / .env.
"""

import argparse
import sys
import time

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import create_db_engine
from app.retrieval import build_retriever
from app.retrieval.errors import SearchError
from app.retrieval.filters import NO_FILTERS, SearchFilters, filters_from_query
from app.retrieval.retriever import CANDIDATES, TOP_K
from app.retrieval.search import normalise_query

PREVIEW_CHARS = 160


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.retrieval",
        description="Hybrid search + reranking of the F1 corpus.",
    )
    parser.add_argument("query", help="the question or search words")
    parser.add_argument(
        "--limit",
        type=int,
        default=TOP_K,
        help=f"results to show (1–{CANDIDATES}, default {TOP_K})",
    )
    parser.add_argument(
        "--no-rerank", action="store_true", help="show the hybrid order, not reranked"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--season",
        type=int,
        action="append",
        help="filter on this season (repeatable); default: years in the query",
    )
    group.add_argument(
        "--no-filters", action="store_true", help="don't filter on years in the query"
    )
    parser.add_argument(
        "--show-text", action="store_true", help="print each chunk's full text"
    )
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        query = normalise_query(args.query)
        if not 1 <= args.limit <= CANDIDATES:
            raise ValueError(f"--limit must be between 1 and {CANDIDATES}")
        if args.no_filters:
            filters = NO_FILTERS
        elif args.season:
            filters = SearchFilters(seasons=tuple(args.season))
        else:
            filters = filters_from_query(query)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_db_engine(settings)
    retriever = build_retriever(settings, rerank=not args.no_rerank)
    try:
        with Session(engine) as session:
            started = time.perf_counter()
            results = retriever.retrieve(
                session, query, filters=filters, top_k=args.limit
            )
            elapsed = time.perf_counter() - started
    except SearchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    seasons = ", ".join(map(str, filters.seasons)) or "none"
    reranked = any(r.rerank_score is not None for r in results)
    print(
        f"{len(results)} results in {elapsed:.2f}s "
        f"(season filter: {seasons}; reranked: {'yes' if reranked else 'no'})\n"
    )
    for rank, result in enumerate(results, start=1):
        print(f"{rank:2}. {result.heading}")
        rerank = (
            "" if result.rerank_score is None else f"  rerank {result.rerank_score:.2f}"
        )
        print(
            f"    {result.score:.4f}{rerank}  [{', '.join(result.signals)}]  "
            f"{result.source_url}"
        )
        body = result.text
        if not args.show_text and len(body) > PREVIEW_CHARS:
            body = body[:PREVIEW_CHARS] + "…"
        print(f"    {body}\n")
    return 0


if __name__ == "__main__":
    sys.exit(run())
