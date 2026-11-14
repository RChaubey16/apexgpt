"""Polite MediaWiki API client for English Wikipedia (stdlib HTTP).

Follows Wikimedia's API etiquette (https://www.mediawiki.org/wiki/API:Etiquette):

- requests are serial, at least `min_interval` seconds apart;
- a descriptive User-Agent with contact details (WIKI_USER_AGENT) is required;
- `maxlag=5` is sent, and "maxlag" replies are retried after Retry-After;
- 429/5xx/network errors are retried with backoff (common.http.open_url);
- revision lookups are batched, 50 titles per request.

Only two calls are used:

- `current_revisions(titles)`: page id + latest revision id per title,
  following normalisation ("ayrton senna" -> "Ayrton Senna") and redirects
  ("Schumi" -> "Michael Schumacher"); missing pages map to None.
- `parse(title)`: the rendered article HTML (action=parse) plus its revision id.
  Cleaning (tables, infoboxes, citations, ...) is the cleaner's job (F2.3).
"""

import json
import logging
import time
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from pydantic import BaseModel, Field, ValidationError

from common.http import Opener, open_url, retry_after
from narrative.errors import WikiError

logger = logging.getLogger(__name__)

API_URL = "https://en.wikipedia.org/w/api.php"
ARTICLE_URL = "https://en.wikipedia.org/wiki/"
BATCH_SIZE = 50  # MediaWiki's limit for titles per query (non-bot clients)
MAX_RESPONSE_BYTES = 20_000_000
MAX_MAXLAG_RETRIES = 5
MAXLAG_SECONDS = 5
# Characters MediaWiki never allows in titles ("|" would also split a batch).
_ILLEGAL_TITLE_CHARS = set("#<>[]{}|")


def validate_title(title: str) -> str:
    """Normalise a title like MediaWiki does (spaces, first letter) and check it.

    Raises ValueError for a title MediaWiki can't hold.
    """
    cleaned = " ".join(title.replace("_", " ").split())
    if not cleaned:
        raise ValueError("title is empty")
    if len(cleaned.encode("utf-8")) > 255:
        raise ValueError(f"title is longer than 255 bytes: {cleaned[:40]!r}…")
    if _ILLEGAL_TITLE_CHARS & set(cleaned):
        raise ValueError(f"title contains a character MediaWiki forbids: {cleaned!r}")
    # English Wikipedia capitalises the first letter of every title.
    return cleaned[0].upper() + cleaned[1:]


def article_url(title: str) -> str:
    return ARTICLE_URL + urllib.parse.quote(title.replace(" ", "_"), safe="()_,'-.!:/")


@dataclass(frozen=True)
class PageRef:
    """A page's current identity: title after redirects, page id, latest revision."""

    title: str
    pageid: int
    revid: int


@dataclass(frozen=True)
class Article:
    requested_title: str
    title: str
    pageid: int
    revid: int
    html: str

    @property
    def url(self) -> str:
        return article_url(self.title)


# --- response shapes (formatversion=2) ---


class _Revision(BaseModel):
    revid: int


class _QueryPage(BaseModel):
    title: str
    pageid: int | None = None
    missing: bool = False
    invalid: bool = False
    revisions: list[_Revision] = []


class _Mapping(BaseModel):
    from_: str = Field(alias="from")  # "from" is a Python keyword
    to: str


class _Query(BaseModel):
    normalized: list[_Mapping] = []
    redirects: list[_Mapping] = []
    pages: list[_QueryPage] = []


class _Parse(BaseModel):
    title: str
    pageid: int
    revid: int
    text: str


class WikiClient:
    def __init__(
        self,
        user_agent: str,
        min_interval: float = 1.0,
        opener: Opener = urllib.request.urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._user_agent = user_agent
        self._min_interval = min_interval
        self._opener = opener
        self._clock = clock
        self._sleep = sleep
        self._last_request: float | None = None
        self.requests_made = 0

    def _throttle(self) -> None:
        if self._last_request is not None:
            wait = self._min_interval - (self._clock() - self._last_request)
            if wait > 0:
                self._sleep(wait)
        self._last_request = self._clock()

    def _get(self, params: dict[str, str]) -> dict:
        query = {
            **params,
            "format": "json",
            "formatversion": "2",
            "maxlag": str(MAXLAG_SECONDS),
        }
        url = f"{API_URL}?{urllib.parse.urlencode(query)}"
        for attempt in range(MAX_MAXLAG_RETRIES + 1):
            self._throttle()
            self.requests_made += 1
            with open_url(
                url, self._opener, user_agent=self._user_agent, error=WikiError
            ) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
                headers = getattr(response, "headers", None)
            if len(body) > MAX_RESPONSE_BYTES:
                raise WikiError("MediaWiki response is unexpectedly large")
            try:
                data = json.loads(body)
            except ValueError:
                raise WikiError("MediaWiki returned invalid JSON") from None
            error = data.get("error") if isinstance(data, dict) else None
            if not (error and error.get("code") == "maxlag"):
                return data
            if attempt < MAX_MAXLAG_RETRIES:
                delay = retry_after(headers) or MAXLAG_SECONDS
                logger.info("Wikipedia servers lagged; retrying in %ss", delay)
                self._sleep(delay)
        raise WikiError("Wikipedia servers stayed lagged; try again later")

    def current_revisions(self, titles: Iterable[str]) -> dict[str, PageRef | None]:
        """Requested title -> current page (after redirects), or None if missing."""
        wanted = list(dict.fromkeys(validate_title(t) for t in titles))
        result: dict[str, PageRef | None] = {}
        for start in range(0, len(wanted), BATCH_SIZE):
            batch = wanted[start : start + BATCH_SIZE]
            data = self._get(
                {
                    "action": "query",
                    "prop": "revisions",
                    "rvprop": "ids",
                    "redirects": "1",
                    "titles": "|".join(batch),
                }
            )
            if "error" in data:
                raise WikiError(f"MediaWiki error: {data['error'].get('code', '?')}")
            try:
                query = _Query.model_validate(data.get("query", {}))
            except ValidationError as exc:
                raise WikiError(f"unexpected MediaWiki query response: {exc}") from None
            result.update(_resolve(batch, query))
        return result

    def parse(self, title: str) -> Article | None:
        """The article's rendered HTML, following redirects; None if it doesn't exist."""
        requested = validate_title(title)
        data = self._get(
            {
                "action": "parse",
                "page": requested,
                "prop": "text|revid",
                "redirects": "1",
                "disableeditsection": "1",
                "disabletoc": "1",
            }
        )
        if "error" in data:
            code = data["error"].get("code", "?")
            if code in ("missingtitle", "invalidtitle"):
                return None
            raise WikiError(f"MediaWiki error for {requested!r}: {code}")
        try:
            parsed = _Parse.model_validate(data.get("parse", {}))
        except ValidationError as exc:
            raise WikiError(
                f"unexpected MediaWiki parse response for {requested!r}: {exc}"
            ) from None
        return Article(
            requested_title=requested,
            title=parsed.title,
            pageid=parsed.pageid,
            revid=parsed.revid,
            html=parsed.text,
        )


def _resolve(batch: Sequence[str], query: _Query) -> dict[str, PageRef | None]:
    """Map each requested title through normalisation and redirects to its page."""
    normalized = {m.from_: m.to for m in query.normalized}
    redirects = {m.from_: m.to for m in query.redirects}
    pages = {p.title: p for p in query.pages}
    resolved: dict[str, PageRef | None] = {}
    for requested in batch:
        title = normalized.get(requested, requested)
        seen = {title}
        while title in redirects:
            title = redirects[title]
            if title in seen:  # redirect loop
                break
            seen.add(title)
        page = pages.get(title)
        if (
            page is None
            or page.missing
            or page.invalid
            or page.pageid is None
            or not page.revisions
        ):
            resolved[requested] = None
        else:
            resolved[requested] = PageRef(
                page.title, page.pageid, page.revisions[0].revid
            )
    return resolved
