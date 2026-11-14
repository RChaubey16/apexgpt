"""On-disk cache of fetched Wikipedia articles (data/wikipedia/, git-ignored).

One JSON file per requested title: the rendered HTML plus the resolved title,
page id, revision id and URL (needed for CC BY-SA attribution). Writes are
atomic (temp file + rename), so an interrupted run never leaves half a file;
an unreadable file is treated as not cached and fetched again.
"""

import hashlib
import json
import logging
import os
import re
import tempfile
from pathlib import Path

from narrative.wiki import Article

logger = logging.getLogger(__name__)

_SLUG = re.compile(r"[^a-z0-9]+")


class ArticleCache:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def path_for(self, requested_title: str) -> Path:
        # Readable slug + hash: unique, filesystem-safe, case-sensitive titles kept apart.
        slug = _SLUG.sub("-", requested_title.lower()).strip("-")[:60] or "article"
        digest = hashlib.sha256(requested_title.encode("utf-8")).hexdigest()[:10]
        return self.directory / f"{slug}-{digest}.json"

    def get(self, requested_title: str) -> Article | None:
        path = self.path_for(requested_title)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            article = Article(
                requested_title=data["requested_title"],
                title=data["title"],
                pageid=int(data["pageid"]),
                revid=int(data["revid"]),
                html=data["html"],
            )
        except (OSError, ValueError, KeyError, TypeError):
            logger.warning("Ignoring unreadable cache file %s", path.name)
            return None
        if article.requested_title != requested_title:
            logger.warning("Ignoring cache file %s for a different title", path.name)
            return None
        return article

    def put(self, article: Article) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.path_for(article.requested_title)
        payload = {
            "requested_title": article.requested_title,
            "title": article.title,
            "pageid": article.pageid,
            "revid": article.revid,
            "url": article.url,
            "html": article.html,
        }
        fd, tmp = tempfile.mkstemp(dir=self.directory, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return path
