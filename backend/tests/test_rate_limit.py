"""Per-IP rate limits (F4.4): parsing, the limiter, and the 429 on the routes."""

import logging

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.routes.chat import get_orchestrator
from app.core.rate_limit import RateLimiter, parse_limits
from app.db.session import get_session
from app.main import create_app
from tests.conftest import make_settings
from tests.test_chat_api import FakeOrchestrator
from tests.test_feedback_api import BODY, FakeSession

# --- parsing and settings ---


def test_limits_parse() -> None:
    assert [str(i) for i in parse_limits(" 6/minute; 100/day ")] == [
        "6 per 1 minute",
        "100 per 1 day",
    ]
    assert parse_limits("") == () and parse_limits("  ") == ()


@pytest.mark.parametrize("spec", ["abc", "6", "6/fortnight", "0/minute", "-1/day"])
def test_bad_limits_are_rejected(spec: str) -> None:
    with pytest.raises(ValueError, match="invalid rate limit"):
        parse_limits(spec)


def test_settings_reject_a_bad_limit_at_startup() -> None:
    with pytest.raises(ValidationError, match="RATE_LIMIT|invalid rate limit"):
        make_settings(rate_limit_chat="lots")


@pytest.mark.parametrize(
    ("field", "value"),
    [("answer_cache_size", -1), ("answer_cache_size", 10_001),
     ("answer_cache_ttl_seconds", 59), ("answer_cache_ttl_seconds", 604_801)],
)  # fmt: skip
def test_cache_settings_are_bounded(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        make_settings(**{field: value})


def test_defaults() -> None:
    settings = make_settings()
    assert settings.rate_limit_chat == "6/minute;100/day"
    assert settings.rate_limit_feedback == "30/minute;500/day"
    assert (settings.answer_cache_size, settings.answer_cache_ttl_seconds) == (
        256,
        86_400,
    )


# --- the limiter ---


def test_the_limiter_counts_per_scope_and_key() -> None:
    limiter = RateLimiter({"chat": parse_limits("2/minute"), "feedback": ()})

    assert limiter.hit("chat", "a") is None
    assert limiter.hit("chat", "a") is None
    rejection = limiter.hit("chat", "a")
    assert rejection is not None
    assert rejection.limit == "2 per 1 minute" and 1 <= rejection.retry_after <= 60
    assert limiter.hit("chat", "b") is None  # another client
    assert all(limiter.hit("feedback", "a") is None for _ in range(50))  # no limit
    assert limiter.hit("unknown", "a") is None

    limiter.reset()
    assert limiter.hit("chat", "a") is None


def test_every_window_applies() -> None:
    limiter = RateLimiter({"chat": parse_limits("10/minute;3/day")})

    results = [limiter.hit("chat", "a") for _ in range(4)]

    assert results[:3] == [None, None, None]
    assert results[3] is not None and results[3].limit == "3 per 1 day"
    assert results[3].retry_after > 60


# --- the routes ---


def app_with(**settings):
    app = create_app(make_settings(environment="test", **settings))
    app.dependency_overrides[get_orchestrator] = lambda: FakeOrchestrator()
    app.dependency_overrides[get_session] = lambda: FakeSession()
    return app


def test_chat_is_limited_per_client(caplog) -> None:
    app = app_with(rate_limit_chat="2/minute")
    alice = TestClient(app, client=("203.0.113.1", 1000))
    bob = TestClient(app, client=("203.0.113.2", 1000))
    logging.getLogger().addHandler(caplog.handler)

    codes = [
        alice.post("/api/chat", json={"question": "q"}).status_code for _ in range(3)
    ]
    over = alice.post("/api/chat", json={"question": "q"})

    assert codes == [200, 200, 429]
    assert over.status_code == 429
    assert over.json()["detail"].startswith("Too many requests; please try again in ")
    assert 1 <= int(over.headers["retry-after"]) <= 60
    assert bob.post("/api/chat", json={"question": "q"}).status_code == 200
    assert "Rate limited: chat (2 per 1 minute)" in caplog.text
    assert "203.0.113.1" not in caplog.text


def test_a_limited_chat_never_reaches_the_orchestrator() -> None:
    fake = FakeOrchestrator()
    app = app_with(rate_limit_chat="1/minute")
    app.dependency_overrides[get_orchestrator] = lambda: fake
    client = TestClient(app)

    client.post("/api/chat", json={"question": "first"})
    client.post("/api/chat", json={"question": "second"})

    assert fake.questions == ["first"]


def test_feedback_has_its_own_limit() -> None:
    client = TestClient(
        app_with(rate_limit_chat="1/minute", rate_limit_feedback="2/minute")
    )

    assert client.post("/api/chat", json={"question": "q"}).status_code == 200
    codes = [client.post("/api/feedback", json=BODY).status_code for _ in range(3)]

    assert codes == [201, 201, 429]
    assert client.post("/api/chat", json={"question": "q"}).status_code == 429


def test_a_blank_limit_means_unlimited() -> None:
    client = TestClient(app_with(rate_limit_chat=""))

    assert {client.post("/api/chat", json={"question": "q"}).status_code
            for _ in range(20)} == {200}  # fmt: skip


def test_health_is_never_limited() -> None:
    client = TestClient(
        app_with(rate_limit_chat="1/minute", rate_limit_feedback="1/minute")
    )

    assert {client.get("/health").status_code for _ in range(20)} == {200}


def test_forwarded_headers_from_a_client_are_ignored() -> None:
    """Only uvicorn (trusting FORWARDED_ALLOW_IPS) may set the client address."""
    client = TestClient(app_with(rate_limit_chat="1/minute"))

    first = client.post("/api/chat", json={"question": "q"},
                        headers={"X-Forwarded-For": "198.51.100.1"})  # fmt: skip
    second = client.post("/api/chat", json={"question": "q"},
                         headers={"X-Forwarded-For": "198.51.100.2"})  # fmt: skip

    assert (first.status_code, second.status_code) == (200, 429)


def test_each_app_has_its_own_counters() -> None:
    one, two = TestClient(app_with(rate_limit_chat="1/minute")), TestClient(
        app_with(rate_limit_chat="1/minute")
    )

    assert one.post("/api/chat", json={"question": "q"}).status_code == 200
    assert two.post("/api/chat", json={"question": "q"}).status_code == 200


def test_the_browser_can_read_retry_after() -> None:
    client = TestClient(app_with(rate_limit_chat="1/minute"))
    origin = {"Origin": "http://localhost:3000"}

    client.post("/api/chat", json={"question": "q"}, headers=origin)
    over = client.post("/api/chat", json={"question": "q"}, headers=origin)

    assert over.status_code == 429
    assert "retry-after" in over.headers["access-control-expose-headers"].lower()
