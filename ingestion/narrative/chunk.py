"""Chunk the cleaned articles and write data/narrative/chunks.jsonl.

    cd ingestion
    uv run python -m narrative.chunk                                   # chunk everything
    uv run python -m narrative.chunk --show "1990 Japanese Grand Prix" # print one, write nothing

Reads data/narrative/articles.jsonl (from `python -m narrative.clean`).
Offline: no network or database. Takes a few seconds.
"""

import argparse
import logging
import sys
from collections import Counter

from pydantic import ValidationError

from narrative.articles import articles_path, read_articles
from narrative.chunker import ChunkError
from narrative.chunks import ChunkRecord, chunk_article, chunks_path, write_chunks
from narrative.config import WikiSettings
from narrative.wiki import validate_title
from structured.errors import IngestionError

logger = logging.getLogger("narrative.chunk")

# Chunks this small are counted in the report (mostly intro-only articles).
SMALL_TOKENS = 100


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m narrative.chunk",
        description="Split the cleaned Wikipedia articles into retrieval chunks.",
    )
    parser.add_argument(
        "--show",
        metavar="TITLE",
        help="print one article's chunks; write nothing",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    if args.show is not None:
        try:
            args.show = validate_title(args.show)
        except ValueError as exc:
            parser.error(str(exc))
    return args


def _show(chunks: list[ChunkRecord]) -> None:
    for chunk in chunks:
        print(f"\n## [{chunk.index}] {chunk.heading} (~{chunk.tokens} tokens)\n")
        print(chunk.text)


def _percentile(values: list[int], fraction: float) -> int:
    return values[min(int(len(values) * fraction), len(values) - 1)]


def _report(chunks: list[ChunkRecord], articles: int, output: object) -> None:
    by_depth = Counter(chunk.depth.value for chunk in chunks)
    for depth, count in sorted(by_depth.items()):
        logger.info("  %-8s %6d chunks", depth, count)
    tokens = sorted(chunk.tokens for chunk in chunks)
    size = sum(len(chunk.text.encode()) for chunk in chunks)
    logger.info(
        "Chunked %d articles into %d chunks -> %s", articles, len(chunks), output
    )
    if tokens:
        logger.info(
            "  ~tokens per chunk: median %d, 90%% %d, max %d; %d under %d; "
            "%.1f MB of text",
            _percentile(tokens, 0.5),
            _percentile(tokens, 0.9),
            tokens[-1],
            sum(t < SMALL_TOKENS for t in tokens),
            SMALL_TOKENS,
            size / 1_000_000,
        )


def run(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        settings = WikiSettings()
    except ValidationError as exc:
        for error in exc.errors():
            logger.error(
                "Invalid setting %s: %s", ".".join(map(str, error["loc"])), error["msg"]
            )
        return 2

    chunks: list[ChunkRecord] = []
    articles = 0
    problems: list[str] = []
    try:
        for article in read_articles(articles_path(settings.data_dir)):
            if args.show is not None and article.title != args.show:
                continue
            articles += 1
            try:
                chunks.extend(chunk_article(article))
            except ChunkError as exc:
                problems.append(str(exc))
    except IngestionError as exc:
        logger.error("%s", exc)
        return 1

    if problems:
        # Never replace a complete file with a partial corpus.
        logger.error(
            "%d articles could not be chunked (nothing written):", len(problems)
        )
        for problem in problems:
            logger.error("  %s", problem)
        return 1

    if args.show is not None:
        if not articles:
            logger.error("%r is not in the cleaned articles", args.show)
            return 1
        _show(chunks)
        return 0

    output = chunks_path(settings.data_dir)
    try:
        write_chunks(output, chunks)
    except OSError as exc:
        logger.error("Cannot write %s: %s", output, exc.strerror or type(exc).__name__)
        return 1
    _report(chunks, articles, output)
    return 0


if __name__ == "__main__":
    sys.exit(run())
