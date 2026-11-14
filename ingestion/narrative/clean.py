"""Clean every selected article and write data/narrative/articles.jsonl.

    cd ingestion
    uv run python -m narrative.clean                          # clean the whole selection
    uv run python -m narrative.clean --show "1990 Japanese Grand Prix"   # print one, write nothing

Reads the selection (data/narrative/selection.json, from `python -m narrative.select`)
and the fetched HTML (data/wikipedia/, from `python -m narrative --selection`).
Offline: no network or database. Takes ~2 minutes for the full corpus.
"""

import argparse
import logging
import re
import sys
from collections import Counter
from collections.abc import Iterator

from pydantic import ValidationError

from narrative.articles import (
    ArticleRecord,
    SectionRecord,
    articles_path,
    write_articles,
)
from narrative.cache import ArticleCache
from narrative.cleaner import CleanError, clean_article
from narrative.config import WikiSettings
from narrative.manifest import manifest_path, read_manifest
from narrative.selection import Selected
from narrative.wiki import validate_title
from structured.errors import IngestionError

logger = logging.getLogger("narrative.clean")

# Articles this short are reported (a stub, or a cleaning rule gone wrong).
SHORT_WORDS = 20
# Rough tokens per word for English prose, for the size estimate.
TOKENS_PER_WORD = 1.33
# Markup that should never survive cleaning; reported if it does (a page
# layout the cleaner doesn't know yet).
LEFTOVER_MARKUP = re.compile(
    r"mw-parser-output|\.mw-|\{[a-z-]+:[^}]*\}|\[\d+\]|\[citation needed\]"
    r"|\\displaystyle|\d+°\d+′\d*″?[NS]"
)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m narrative.clean",
        description="Clean the selected Wikipedia articles for chunking.",
    )
    parser.add_argument(
        "--show",
        metavar="TITLE",
        help="print one selected article's cleaned sections; write nothing",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    if args.show is not None:
        try:
            args.show = validate_title(args.show)
        except ValueError as exc:
            parser.error(str(exc))
    return args


class _Run:
    def __init__(self, cache: ArticleCache) -> None:
        self.cache = cache
        self.problems: list[str] = []
        self.short: list[str] = []
        self.words: Counter[str] = Counter()
        self.articles: Counter[str] = Counter()
        self.leftovers: list[str] = []

    def record(self, article: Selected) -> ArticleRecord | None:
        cached = self.cache.get(article.title)
        if cached is None:
            self.problems.append(f"{article.title!r} is not fetched yet")
            return None
        if cached.pageid != article.pageid:
            self.problems.append(
                f"{article.title!r}: the cached page ({cached.pageid}) isn't the selected "
                f"one ({article.pageid}); fetch it again with --refresh"
            )
            return None
        try:
            cleaned = clean_article(cached.html, article.depth, article.anchor)
        except CleanError as exc:
            self.problems.append(f"{article.title!r}: {exc}")
            return None
        record = ArticleRecord(
            title=cached.title,
            pageid=cached.pageid,
            revid=cached.revid,
            url=cached.url,
            depth=article.depth,
            kinds=article.kinds,
            season=article.season,
            race_id=article.race_id,
            circuit_id=article.circuit_id,
            driver_ids=article.driver_ids,
            constructor_ids=article.constructor_ids,
            topic=article.topic,
            sections=tuple(
                SectionRecord(path=s.path, text=s.text) for s in cleaned.sections
            ),
        )
        self.words[article.depth.value] += record.words
        self.articles[article.depth.value] += 1
        if record.words < SHORT_WORDS:
            self.short.append(f"{article.title!r} ({record.words} words)")
        for section in record.sections:
            if match := LEFTOVER_MARKUP.search(section.text):
                start = max(match.start() - 30, 0)
                self.leftovers.append(
                    f"{article.title!r} [{' > '.join(section.path) or 'lead'}]: "
                    f"…{section.text[start : match.end() + 30]}…"
                )
        return record

    def records(self, articles: tuple[Selected, ...]) -> Iterator[ArticleRecord]:
        for article in articles:
            if (record := self.record(article)) is not None:
                yield record


def _show(record: ArticleRecord) -> None:
    print(f"{record.title} [{record.depth.value}] {record.words} words · {record.url}")
    for section in record.sections:
        heading = " > ".join(section.path) or "(lead)"
        print(f"\n## {heading}\n\n{section.text}")


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

    run_ = _Run(ArticleCache(settings.data_dir / "wikipedia"))
    try:
        manifest = read_manifest(manifest_path(settings.data_dir))
    except IngestionError as exc:
        logger.error("%s", exc)
        return 1

    if args.show is not None:
        article = next((a for a in manifest.articles if a.title == args.show), None)
        if article is None:
            logger.error("%r is not in the selection", args.show)
            return 1
        record = run_.record(article)
        if record is None:
            logger.error("%s", run_.problems[0])
            return 1
        _show(record)
        return 0

    records = list(run_.records(manifest.articles))
    if run_.problems:
        # Never replace a complete file with a partial corpus.
        logger.error(
            "%d articles could not be cleaned (nothing written):", len(run_.problems)
        )
        for problem in run_.problems:
            logger.error("  %s", problem)
        return 1

    output = articles_path(settings.data_dir)
    try:
        written = write_articles(output, records)
    except OSError as exc:
        logger.error("Cannot write %s: %s", output, exc.strerror or type(exc).__name__)
        return 1

    for depth, count in run_.articles.items():
        logger.info(
            "  %-8s %5d articles %10s words", depth, count, f"{run_.words[depth]:,}"
        )
    total = sum(run_.words.values())
    logger.info(
        "Cleaned %d articles: %s words (~%s tokens) -> %s",
        written,
        f"{total:,}",
        f"{int(total * TOKENS_PER_WORD):,}",
        output,
    )
    if run_.short:
        logger.warning(
            "%d articles kept under %d words (stubs?): %s",
            len(run_.short),
            SHORT_WORDS,
            ", ".join(run_.short[:10]) + (" ..." if len(run_.short) > 10 else ""),
        )
    if run_.leftovers:
        logger.warning(
            "%d sections still contain markup (a page layout the cleaner may not handle):",
            len(run_.leftovers),
        )
        for leftover in run_.leftovers[:10]:
            logger.warning("  %s", leftover)
    return 0


if __name__ == "__main__":
    sys.exit(run())
