import urllib.error
from email.message import Message

import pytest

from common import http as common_http
from narrative import wiki
from narrative.errors import WikiError
from narrative.wiki import PageRef, WikiClient, article_url, validate_title
from tests.narrative.fake_wiki import FakeWiki

UA = "test-agent/1.0 (tests)"


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def fake() -> FakeWiki:
    w = FakeWiki()
    w.add("Ayrton Senna", 1, 101)
    w.add("Michael Schumacher", 2, 202)
    w.redirects["Schumi"] = "Michael Schumacher"
    return w


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture(autouse=True)
def no_http_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(common_http.time, "sleep", lambda s: None)


def _client(fake: FakeWiki, clock: FakeClock, interval: float = 1.0) -> WikiClient:
    return WikiClient(UA, interval, opener=fake, clock=clock, sleep=clock.sleep)


# --- titles and URLs ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Ayrton Senna", "Ayrton Senna"),
        ("  ayrton_senna ", "Ayrton senna"),
        ("1989   Japanese Grand Prix", "1989 Japanese Grand Prix"),
        ("São Paulo Grand Prix", "São Paulo Grand Prix"),
    ],
)
def test_validate_title(raw: str, expected: str) -> None:
    assert validate_title(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "A|B", "A#section", "x" * 256, "[[Link]]"])
def test_invalid_titles(raw: str) -> None:
    with pytest.raises(ValueError):
        validate_title(raw)


def test_article_url() -> None:
    assert (
        article_url("Kimi Räikkönen")
        == "https://en.wikipedia.org/wiki/Kimi_R%C3%A4ikk%C3%B6nen"
    )
    assert article_url("Toro Rosso (racing team)").endswith("/Toro_Rosso_(racing_team)")


# --- requests ---


def test_requests_carry_user_agent_maxlag_and_json_format(
    fake: FakeWiki, clock: FakeClock
) -> None:
    _client(fake, clock).parse("Ayrton Senna")

    assert fake.user_agents == [UA]
    params = fake.calls[0]
    assert (params["maxlag"], params["format"], params["formatversion"]) == (
        "5",
        "json",
        "2",
    )
    assert params["redirects"] == "1"


def test_requests_are_throttled(fake: FakeWiki, clock: FakeClock) -> None:
    client = _client(fake, clock, interval=1.5)

    client.parse("Ayrton Senna")
    clock.now += 0.5  # half a second of work between requests
    client.parse("Michael Schumacher")
    client.parse("Ayrton Senna")

    assert clock.sleeps == [1.0, 1.5]


def test_maxlag_replies_are_retried_after_retry_after(
    fake: FakeWiki, clock: FakeClock
) -> None:
    fake.queued.append(({"error": {"code": "maxlag", "lag": 7}}, {"Retry-After": "3"}))

    article = _client(fake, clock, interval=0.1).parse("Ayrton Senna")

    assert article is not None
    assert len(fake.calls) == 2
    assert 3 in clock.sleeps


def test_persistent_maxlag_gives_up(fake: FakeWiki, clock: FakeClock) -> None:
    fake.queued.extend(
        [({"error": {"code": "maxlag"}}, {})] * (wiki.MAX_MAXLAG_RETRIES + 1)
    )

    with pytest.raises(WikiError, match="stayed lagged"):
        _client(fake, clock).parse("Ayrton Senna")


def test_http_errors_are_retried_then_reported(clock: FakeClock) -> None:
    attempts = []

    def failing(request: object, timeout: float) -> None:
        attempts.append(1)
        raise urllib.error.HTTPError("https://x", 503, "busy", Message(), None)

    with pytest.raises(WikiError, match="HTTP 503 from en.wikipedia.org"):
        WikiClient(UA, opener=failing, clock=clock, sleep=clock.sleep).parse("A")
    assert len(attempts) == common_http.DEFAULT_ATTEMPTS


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (
            {"error": {"code": "badtoken"}},
            "MediaWiki error for 'Ayrton Senna': badtoken",
        ),
        ({"parse": {"title": "X"}}, "unexpected MediaWiki parse response"),
    ],
)
def test_unexpected_parse_replies(
    fake: FakeWiki, clock: FakeClock, reply: dict, message: str
) -> None:
    fake.queued.append((reply, {}))

    with pytest.raises(WikiError, match=message):
        _client(fake, clock).parse("Ayrton Senna")


def test_invalid_json(clock: FakeClock) -> None:
    from tests.narrative.fake_wiki import Response

    client = WikiClient(
        UA,
        opener=lambda r, timeout: Response(b"<html>"),
        clock=clock,
        sleep=clock.sleep,
    )

    with pytest.raises(WikiError, match="invalid JSON"):
        client.parse("A")


def test_oversized_response(clock: FakeClock, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.narrative.fake_wiki import Response

    monkeypatch.setattr(wiki, "MAX_RESPONSE_BYTES", 10)
    client = WikiClient(
        UA,
        opener=lambda r, timeout: Response(b"{" + b" " * 20 + b"}"),
        clock=clock,
        sleep=clock.sleep,
    )

    with pytest.raises(WikiError, match="unexpectedly large"):
        client.parse("A")


# --- parse ---


def test_parse_follows_redirects(fake: FakeWiki, clock: FakeClock) -> None:
    article = _client(fake, clock).parse("Schumi")

    assert article is not None
    assert (article.requested_title, article.title, article.revid) == (
        "Schumi",
        "Michael Schumacher",
        202,
    )
    assert article.url == "https://en.wikipedia.org/wiki/Michael_Schumacher"


def test_parse_missing_page(fake: FakeWiki, clock: FakeClock) -> None:
    assert _client(fake, clock).parse("No Such Page") is None


# --- revisions ---


def test_current_revisions_resolves_normalisation_redirects_and_missing(
    fake: FakeWiki, clock: FakeClock
) -> None:
    revisions = _client(fake, clock).current_revisions(
        ["Ayrton Senna", "Schumi", "Nope"]
    )

    assert revisions == {
        "Ayrton Senna": PageRef("Ayrton Senna", 1, 101),
        "Schumi": PageRef("Michael Schumacher", 2, 202),
        "Nope": None,
    }


def test_current_revisions_flag_disambiguation_pages(
    fake: FakeWiki, clock: FakeClock
) -> None:
    fake.add("Schumacher", 3, 303, disambiguation=True)

    revisions = _client(fake, clock).current_revisions(["Schumacher", "Ayrton Senna"])

    assert revisions["Schumacher"] == PageRef("Schumacher", 3, 303, disambiguation=True)
    assert revisions["Ayrton Senna"].disambiguation is False
    assert fake.calls[0]["prop"] == "revisions|pageprops"
    assert fake.calls[0]["ppprop"] == "disambiguation"


def test_lowercase_titles_resolve_after_normalisation(
    fake: FakeWiki, clock: FakeClock
) -> None:
    fake.add("Ayrton senna lookalike", 3, 303)

    revisions = _client(fake, clock).current_revisions(["ayrton senna lookalike"])

    assert revisions["Ayrton senna lookalike"] == PageRef(
        "Ayrton senna lookalike", 3, 303
    )


def test_current_revisions_are_batched_by_50(fake: FakeWiki, clock: FakeClock) -> None:
    titles = [f"Page {i}" for i in range(120)]
    for i, t in enumerate(titles):
        fake.add(t, 1000 + i, 5000 + i)

    revisions = _client(fake, clock, interval=0.1).current_revisions(titles)

    assert [len(c["titles"].split("|")) for c in fake.calls] == [50, 50, 20]
    assert revisions["Page 119"] == PageRef("Page 119", 1119, 5119)


def test_redirect_loops_resolve_to_missing(clock: FakeClock) -> None:
    fake = FakeWiki()
    fake.queued.append(
        (
            {
                "query": {
                    "redirects": [{"from": "A", "to": "B"}, {"from": "B", "to": "A"}],
                    "pages": [],
                }
            },
            {},
        )
    )

    assert _client(fake, clock).current_revisions(["A"]) == {"A": None}


def test_query_error_is_reported(fake: FakeWiki, clock: FakeClock) -> None:
    fake.queued.append(({"error": {"code": "toomanyvalues"}}, {}))

    with pytest.raises(WikiError, match="toomanyvalues"):
        _client(fake, clock).current_revisions(["A"])
