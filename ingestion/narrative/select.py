"""Build the article selection and write it to data/narrative/selection.json.

    cd ingestion
    uv run python -m narrative.select                # build, resolve on Wikipedia, write
    uv run python -m narrative.select --no-resolve   # offline: build + print counts only
    uv run python -m narrative.select --topics my_topics.yaml --output sel.json

Reads the structured data (DATABASE_URL, loaded by `python -m structured`),
narrative/topics.yaml and narrative/title_overrides.csv. Every dropped title is
logged; a driver or team dropped as a disambiguation page usually needs a line
in title_overrides.csv. Resolving needs WIKI_USER_AGENT: about one batched
MediaWiki request per 50 articles (~50 requests, about a minute).
Then fetch the articles: `uv run python -m narrative --selection`.
"""

import argparse
import logging
import sys
from pathlib import Path

import psycopg
from pydantic import ValidationError

from narrative.config import WikiSettings
from narrative.entities import read_entity_rows
from narrative.manifest import manifest_path, write_manifest
from narrative.overrides import OVERRIDES_FILE, read_overrides
from narrative.selection import (
    Selected,
    resolve_selection,
    select_articles,
    summarise,
)
from narrative.topics import TOPICS_FILE, read_topics
from narrative.wiki import WikiClient
from structured.config import Settings
from structured.errors import IngestionError
from structured.load import connect

logger = logging.getLogger("narrative.select")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m narrative.select",
        description="Choose the Wikipedia articles for the narrative corpus.",
    )
    parser.add_argument(
        "--topics",
        type=Path,
        default=TOPICS_FILE,
        help="curated topics file (default: narrative/topics.yaml)",
    )
    parser.add_argument(
        "--overrides",
        type=Path,
        default=OVERRIDES_FILE,
        help="curated title overrides (default: narrative/title_overrides.csv)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="manifest path (default: <DATA_DIR>/narrative/selection.json)",
    )
    parser.add_argument(
        "--no-resolve",
        action="store_true",
        help="don't contact Wikipedia: print the counts and write nothing",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def _log_dropped(reason: str, articles: list[Selected]) -> None:
    """Every dropped title, with what it was selected as (a handful, normally)."""
    if not articles:
        return
    logger.warning("Dropped %d articles (%s):", len(articles), reason)
    for a in articles:
        logger.warning(
            "  %r (%s, %s)", a.title, "+".join(k.value for k in a.kinds), a.depth.value
        )


def _log_counts(articles: list) -> None:
    counts = summarise(articles)
    logger.info("%d articles", len(articles))
    logger.info(
        "  by depth: %s", ", ".join(f"{k} {v}" for k, v in counts["depth"].items())
    )
    logger.info(
        "  by kind:  %s", ", ".join(f"{k} {v}" for k, v in counts["kind"].items())
    )


def _settings() -> tuple[Settings, WikiSettings] | None:
    try:
        return Settings(), WikiSettings()
    except ValidationError as exc:
        for error in exc.errors():
            logger.error(
                "Invalid setting %s: %s", ".".join(map(str, error["loc"])), error["msg"]
            )
        return None


def run(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = _settings()
    if settings is None:
        return 2
    db, wiki = settings
    if db.database_url is None:
        logger.error("DATABASE_URL is not set (see .env.example)")
        return 2
    if not args.no_resolve and wiki.wiki_user_agent is None:
        logger.error(
            "WIKI_USER_AGENT is not set: Wikimedia asks for a client name and contact "
            "details (see .env.example). Use --no-resolve to check the selection offline."
        )
        return 2

    try:
        topics = read_topics(args.topics)
        overrides = read_overrides(args.overrides)
        try:
            with connect(
                db.database_url.get_secret_value(), db.database_connect_timeout
            ) as conn:
                rows = read_entity_rows(conn)
        except psycopg.Error as exc:
            logger.error("Database error: %s", type(exc).__name__)
            return 1
        if not rows.races:
            logger.error(
                "No races in the database; load the structured data first "
                "(`uv run python -m structured`)"
            )
            return 1

        selection = select_articles(rows, topics, overrides)
        for skipped in selection.skipped:
            logger.warning("Skipped %s: %s", skipped.source, skipped.reason)
        logger.info(
            "Selected from the structured data, %d topics and %d title overrides:",
            len(topics),
            len(overrides),
        )
        _log_counts(selection.articles)
        if args.no_resolve:
            logger.info("--no-resolve: nothing written")
            return 0

        client = WikiClient(wiki.wiki_user_agent, wiki.wiki_min_interval_seconds)
        resolution = resolve_selection(
            selection.articles, client, curated=selection.curated
        )
    except IngestionError as exc:
        logger.error("%s", exc)
        return 1

    _log_dropped("not on Wikipedia", resolution.missing)
    _log_dropped(
        "disambiguation pages; add the right title to title_overrides.csv",
        resolution.disambiguation,
    )
    for requested, title in resolution.merged:
        logger.info("Merged %r into %r (same article)", requested, title)
    logger.info("Resolved on Wikipedia (%d requests):", client.requests_made)
    _log_counts(resolution.articles)

    output = args.output or manifest_path(wiki.data_dir)
    try:
        write_manifest(output, resolution.articles)
    except OSError as exc:
        logger.error("Cannot write %s: %s", output, exc.strerror or type(exc).__name__)
        return 1
    logger.info("Wrote %s", output)
    return 0


if __name__ == "__main__":
    sys.exit(run())
