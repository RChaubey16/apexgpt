"""Run a knowledge search from the command line.

    uv run python -m app.retrieval "Senna Prost Suzuka collision"
    uv run python -m app.retrieval "Lauda 1976" --limit 5 --show-text
    uv run python -m app.retrieval "Lauda crash" --season 1976 --season 1977
    uv run python -m app.retrieval "Lauda 1976" --no-filters   # ignore the year

Uses DATABASE_URL and EMBEDDING_CACHE_DIR from the environment / .env.
"""

import argparse
import sys
import time

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import create_db_engine
from app.retrieval.embedder import FastEmbedQueryEmbedder
from app.retrieval.errors import SearchError
from app.retrieval.filters import NO_FILTERS, SearchFilters, filters_from_query
from app.retrieval.search import MAX_LIMIT, HybridSearcher, normalise_query

PREVIEW_CHARS = 160


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.retrieval", description="Hybrid search of the F1 corpus."
    )
    parser.add_argument("query", help="the question or search words")
    parser.add_argument(
        "--limit", type=int, default=10, help=f"results to show (1–{MAX_LIMIT})"
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
        if not 1 <= args.limit <= MAX_LIMIT:
            raise ValueError(f"--limit must be between 1 and {MAX_LIMIT}")
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
    searcher = HybridSearcher(FastEmbedQueryEmbedder(settings.embedding_cache_dir))
    try:
        with Session(engine) as session:
            started = time.perf_counter()
            results = searcher.search(session, query, filters=filters, limit=args.limit)
            elapsed = time.perf_counter() - started
    except SearchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    seasons = ", ".join(map(str, filters.seasons)) or "none"
    print(f"{len(results)} results in {elapsed:.2f}s (season filter: {seasons})\n")
    for rank, result in enumerate(results, start=1):
        heading = (
            f"{result.title} > {result.section}" if result.section else result.title
        )
        print(f"{rank:2}. {heading}")
        print(
            f"    {result.score:.4f}  [{', '.join(result.signals)}]  {result.source_url}"
        )
        body = result.text
        if not args.show_text and len(body) > PREVIEW_CHARS:
            body = body[:PREVIEW_CHARS] + "…"
        print(f"    {body}\n")
    return 0


if __name__ == "__main__":
    sys.exit(run())
