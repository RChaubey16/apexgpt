"""A fake MediaWiki API for tests: routes requests by their query parameters."""

import io
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from email.message import Message
from typing import Any


class Response(io.BytesIO):
    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        super().__init__(body)
        self.headers = Message()
        for k, v in (headers or {}).items():
            self.headers[k] = v


@dataclass
class Page:
    title: str
    pageid: int
    revid: int
    html: str = "<p>text</p>"


@dataclass
class FakeWiki:
    """Pages by title, redirects (from -> to), and queued special replies."""

    pages: dict[str, Page] = field(default_factory=dict)
    redirects: dict[str, str] = field(default_factory=dict)
    # Replies returned before normal routing (e.g. a maxlag error), in order.
    queued: list[tuple[dict[str, Any], dict[str, str]]] = field(default_factory=list)
    calls: list[dict[str, str]] = field(default_factory=list)
    user_agents: list[str] = field(default_factory=list)

    def add(
        self, title: str, pageid: int, revid: int, html: str = "<p>text</p>"
    ) -> None:
        self.pages[title] = Page(title, pageid, revid, html)

    def __call__(self, request: urllib.request.Request, timeout: float) -> Response:
        assert timeout > 0
        params = dict(
            urllib.parse.parse_qsl(urllib.parse.urlsplit(request.full_url).query)
        )
        self.calls.append(params)
        self.user_agents.append(request.get_header("User-agent"))
        if self.queued:
            body, headers = self.queued.pop(0)
            return Response(json.dumps(body).encode(), headers)
        if params["action"] == "query":
            return Response(
                json.dumps(self._query(params["titles"].split("|"))).encode()
            )
        if params["action"] == "parse":
            return Response(json.dumps(self._parse(params["page"])).encode())
        raise AssertionError(f"unexpected request {params}")

    def _normalise(self, title: str) -> str:
        return title[0].upper() + title[1:]

    def _query(self, titles: list[str]) -> dict[str, Any]:
        normalized, redirects, pages = [], [], {}
        for requested in titles:
            title = self._normalise(requested)
            if title != requested:
                normalized.append({"from": requested, "to": title})
            if title in self.redirects:
                redirects.append({"from": title, "to": self.redirects[title]})
                title = self.redirects[title]
            page = self.pages.get(title)
            if page is None:
                pages[title] = {"ns": 0, "title": title, "missing": True}
            else:
                pages[title] = {
                    "pageid": page.pageid,
                    "ns": 0,
                    "title": page.title,
                    "revisions": [{"revid": page.revid, "parentid": 1}],
                }
        query: dict[str, Any] = {"pages": list(pages.values())}
        if normalized:
            query["normalized"] = normalized
        if redirects:
            query["redirects"] = redirects
        return {"batchcomplete": True, "query": query}

    def _parse(self, title: str) -> dict[str, Any]:
        title = self.redirects.get(title, title)
        page = self.pages.get(title)
        if page is None:
            return {
                "error": {
                    "code": "missingtitle",
                    "info": "The page you specified doesn't exist.",
                }
            }
        return {
            "parse": {
                "title": page.title,
                "pageid": page.pageid,
                "revid": page.revid,
                "text": page.html,
            }
        }
