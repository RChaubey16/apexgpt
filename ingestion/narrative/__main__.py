"""Fetch Wikipedia articles into the local cache (data/wikipedia/).

    cd ingestion
    uv run python -m narrative --title "1989 Japanese Grand Prix" --title "Ayrton Senna"
    uv run python -m narrative --titles-file titles.txt        # one title per line, # comments
    uv run python -m narrative --titles-file titles.txt --refresh   # refetch changed revisions

Needs WIKI_USER_AGENT (Wikimedia asks for contact details); see .env.example.
Article selection (which titles to fetch) arrives in F2.2.
"""

import argparse
import logging
import sys
from pathlib import Path

from pydantic import ValidationError

from narrative.cache import ArticleCache
from narrative.config import WikiSettings
from narrative.fetch import fetch_articles
from narrative.wiki import WikiClient, validate_title
from structured.errors import IngestionError

logger = logging.getLogger("narrative")


def _read_titles(path: Path) -> list[str]:
    titles = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            titles.append(line)
    return titles


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m narrative",
        description="Fetch Wikipedia articles into data/wikipedia/.",
    )
    parser.add_argument(
        "--title", action="append", default=[], help="article title (repeatable)"
    )
    parser.add_argument("--titles-file", type=Path, help="file with one title per line")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="check revisions and refetch changed articles",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    if args.titles_file is not None and not args.titles_file.is_file():
        parser.error(f"--titles-file: no such file: {args.titles_file}")
    titles = list(args.title)
    if args.titles_file is not None:
        titles += _read_titles(args.titles_file)
    if not titles:
        parser.error("give at least one --title or a --titles-file")
    try:
        args.titles = [validate_title(t) for t in titles]
    except ValueError as exc:
        parser.error(str(exc))
    return args


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
    if settings.wiki_user_agent is None:
        logger.error(
            "WIKI_USER_AGENT is not set: Wikimedia asks for a client name and contact "
            "details (see .env.example)"
        )
        return 2

    client = WikiClient(settings.wiki_user_agent, settings.wiki_min_interval_seconds)
    cache = ArticleCache(settings.data_dir / "wikipedia")
    try:
        report = fetch_articles(args.titles, client, cache, refresh=args.refresh)
    except IngestionError as exc:
        logger.error("%s", exc)
        return 1
    for title in report.missing:
        logger.warning("Not on Wikipedia: %s", title)
    logger.info("%s (%d requests)", report.summary(), client.requests_made)
    return 0


if __name__ == "__main__":
    sys.exit(run())
