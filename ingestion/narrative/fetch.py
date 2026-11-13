"""Fetch Wikipedia articles into the local cache.

- Without refresh: cached articles are used as they are; only missing ones are
  fetched (one request each).
- With refresh: current revision ids are looked up in batches of 50; only
  articles whose revision changed (or that aren't cached) are fetched again.

Titles that don't exist on Wikipedia are reported, not treated as errors:
article selection (F2.2) decides what to do about them.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field

from narrative.cache import ArticleCache
from narrative.wiki import WikiClient, validate_title

logger = logging.getLogger(__name__)


@dataclass
class FetchReport:
    fetched: list[str] = field(default_factory=list)  # new to the cache
    updated: list[str] = field(default_factory=list)  # newer revision fetched
    unchanged: list[str] = field(default_factory=list)  # served from the cache
    missing: list[str] = field(default_factory=list)  # no such page

    def summary(self) -> str:
        return (
            f"{len(self.fetched)} fetched, {len(self.updated)} updated, "
            f"{len(self.unchanged)} cached, {len(self.missing)} missing"
        )


def fetch_articles(
    titles: Iterable[str],
    client: WikiClient,
    cache: ArticleCache,
    refresh: bool = False,
) -> FetchReport:
    wanted = list(dict.fromkeys(validate_title(t) for t in titles))
    report = FetchReport()
    cached = {title: cache.get(title) for title in wanted}

    current = client.current_revisions(wanted) if refresh else {}
    for title in wanted:
        entry = cached[title]
        if entry is not None:
            if not refresh:
                report.unchanged.append(title)
                continue
            latest = current.get(title)
            if latest is None:
                # Deleted (or moved without a redirect) since it was cached.
                logger.warning(
                    "%r no longer exists on Wikipedia; keeping the cached copy", title
                )
                report.missing.append(title)
                continue
            if latest.revid == entry.revid:
                report.unchanged.append(title)
                continue
        elif refresh and current.get(title) is None:
            report.missing.append(title)
            continue

        article = client.parse(title)
        if article is None:
            report.missing.append(title)
            continue
        cache.put(article)
        (report.updated if entry is not None else report.fetched).append(title)
        logger.info("Fetched %r (revision %s)", article.title, article.revid)
    return report
