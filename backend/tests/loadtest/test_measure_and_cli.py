"""Load and cold-start measurement, reports and CLI (F6.4). No Docker or backend:
HTTP goes to an in-process transport, docker calls are fakes, the clock is ours."""

import asyncio
import json
import subprocess

import httpx
import pytest

from loadtest import __main__ as cli
from loadtest.measure import (
    Sample,
    StatsSampler,
    ask,
    cold_start,
    mib,
    parse_stats,
    percentile,
    run_scenario,
)
from loadtest.report import render_coldstart, render_load

URL = "http://backend"


class Clock:
    """Advances by `step` seconds every time it is read."""

    def __init__(self, step: float = 0.1) -> None:
        self.now, self.step = 0.0, step

    def __call__(self) -> float:
        self.now += self.step
        return self.now


def sse(*events: tuple[str, dict]) -> bytes:
    return "".join(
        f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events
    ).encode()


ANSWER = sse(
    ("tool", {"name": "search_f1_knowledge", "status": "started"}),
    ("tool", {"name": "search_f1_knowledge", "status": "finished", "ok": True}),
    ("token", {"text": "Hello"}),
    ("token", {"text": " world"}),
    ("done", {"question": "q"}),
)


def client_for(handler) -> httpx.AsyncClient:  # noqa: ANN001
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _ask(
    body: bytes = ANSWER, status: int = 200, clock: Clock | None = None
):  # noqa: ANN202
    async def go():  # noqa: ANN202
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/chat"
            assert json.loads(request.content) == {"question": "Q?"}
            return httpx.Response(status, content=body)

        async with client_for(handler) as client:
            return await ask(client, URL + "/", "Q?", clock or Clock())

    return asyncio.run(go())


# --- one request ------------------------------------------------------------------


def test_a_good_answer_is_timed() -> None:
    result = _ask()
    assert result.outcome == "ok"
    assert result.status == 200
    # The clock moves 100 ms per read: start, first event, tool started, tool
    # finished, first token, (second token: not read), done.
    assert result.first_event_ms == 100
    assert result.first_token_ms == 400  # the first token, not the last
    assert result.done_ms == 500
    assert result.tool_ms == {"search_f1_knowledge": 100}


@pytest.mark.parametrize(
    ("body", "status", "outcome", "error"),
    [
        (b'{"detail": "slow down"}', 429, "http_error", "HTTP 429"),
        (
            sse(("error", {"message": "No model available"})),
            200,
            "answer_error",
            "No model",
        ),
        (sse(("token", {"text": "cut"})), 200, "no_done", "without done"),
    ],
)
def test_failed_answers(body: bytes, status: int, outcome: str, error: str) -> None:
    result = _ask(body, status)
    assert result.outcome == outcome
    assert error in result.error


def test_a_network_failure() -> None:
    async def go():  # noqa: ANN202
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        async with client_for(handler) as client:
            return await ask(client, URL, "Q?")

    result = asyncio.run(go())
    assert (result.outcome, result.error, result.status) == (
        "network",
        "ConnectError",
        None,
    )


def test_malformed_tool_events_are_ignored() -> None:
    body = (
        sse(("tool", {"status": "started"}))
        + b"event: tool\ndata: not json\n\n"
        + sse(("done", {}))
    )
    result = _ask(body)
    assert result.outcome == "ok"
    assert result.tool_ms == {}


# --- docker stats -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("412.5MiB", 412.5),
        ("1.5GiB", 1536.0),
        ("768MB", 768e6 / 2**20),
        ("512KiB", 0.5),
    ],
)
def test_mib(text: str, value: float) -> None:
    assert mib(text) == pytest.approx(value)


@pytest.mark.parametrize("text", ["", "12 parsecs", "MiB"])
def test_bad_sizes(text: str) -> None:
    with pytest.raises(ValueError):
        mib(text)


def test_parse_stats() -> None:
    assert parse_stats("345.6MiB / 768MiB|102.35%\n") == Sample(345.6, 768.0, 102.35)


def test_the_sampler_collects_until_stopped() -> None:
    reads: list[str] = []

    def read(container: str) -> Sample | None:
        reads.append(container)
        return None if len(reads) == 2 else Sample(100.0 + len(reads), 768.0, 50.0)

    async def go() -> StatsSampler:
        async with StatsSampler("box", interval=0.001, read=read) as sampler:
            while len(reads) < 4:
                await asyncio.sleep(0.001)
        return sampler

    sampler = asyncio.run(go())
    assert set(reads) == {"box"}
    assert [s.memory_mib for s in sampler.samples][:3] == [101.0, 103.0, 104.0]


def test_no_container_no_sampling() -> None:
    async def go() -> StatsSampler:
        async with StatsSampler(None, read=pytest.fail) as sampler:
            await asyncio.sleep(0)
        return sampler

    assert asyncio.run(go()).samples == []


# --- scenarios ------------------------------------------------------------------------


def test_percentile() -> None:
    assert percentile([], 95) is None
    assert percentile(list(range(1, 21)), 95) == 19
    assert percentile([7], 50) == 7


def test_a_scenario_asks_every_request_with_bounded_concurrency() -> None:
    in_flight, peak, asked = 0, 0, []

    async def go():  # noqa: ANN202
        nonlocal in_flight, peak

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            asked.append(json.loads(request.content)["question"])
            await asyncio.sleep(0.001)
            in_flight -= 1
            return httpx.Response(200, content=ANSWER)

        async with client_for(handler) as client:
            return await run_scenario(URL, ["a", "b", "c"], 3, 7, client=client)

    scenario = asyncio.run(go())
    assert len(scenario.results) == 7
    assert peak == 3
    assert asked.count("a") == 3  # questions cycle
    summary = scenario.summary()
    assert (summary["ok"], summary["outcomes"]) == (7, {"ok": 7})
    assert summary["retrieval_ms"]["p50"] is not None
    assert summary["peak_memory_mib"] is None  # no container given


def test_a_scenario_summary_with_failures_and_samples() -> None:
    from loadtest.measure import RequestResult, Scenario

    results = [
        RequestResult("a", 200, done_ms=1000, first_token_ms=500, first_event_ms=100),
        RequestResult("b", 200, done_ms=3000, first_token_ms=900, first_event_ms=120),
        RequestResult("c", 429, outcome="http_error", error="HTTP 429: x"),
    ]
    samples = [Sample(300, 768, 90), Sample(410.26, 768, 101)]
    summary = Scenario(2, 3, 30.0, results, samples).summary()
    assert summary["ok"] == 2
    assert summary["outcomes"] == {"ok": 2, "http_error": 1}
    assert summary["throughput_per_minute"] == 4.0
    assert summary["done_ms"] == {"p50": 1000, "p95": 3000, "max": 3000}
    assert (summary["peak_memory_mib"], summary["memory_limit_mib"]) == (410.3, 768)
    assert summary["errors"] == ["HTTP 429: x"]


@pytest.mark.parametrize(
    ("users", "requests", "questions"), [(0, 1, ["a"]), (1, 0, ["a"]), (1, 1, [])]
)
def test_bad_scenarios(users: int, requests: int, questions: list[str]) -> None:
    with pytest.raises(ValueError):
        asyncio.run(run_scenario(URL, questions, users, requests))


# --- cold start ------------------------------------------------------------------------


def _cold(
    handler, restart=lambda c: None, timeout: float = 5.0
):  # noqa: ANN001, ANN202
    original = httpx.AsyncClient

    class Patched(original):
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    httpx.AsyncClient = Patched
    try:
        return asyncio.run(
            cold_start(
                URL,
                "box",
                ("first?", "second?"),
                timeout=timeout,
                restart=restart,
                read_stats=lambda c: Sample(350.0, 768.0, 5.0),
            )
        )
    finally:
        httpx.AsyncClient = original


def test_cold_start_waits_for_health_then_times_two_answers() -> None:
    calls: list[str] = []
    restarted: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/health" and calls.count("/health") < 3:
            raise httpx.ConnectError("not up yet")
        if request.url.path == "/api/chat":
            return httpx.Response(200, content=ANSWER)
        return httpx.Response(200, json={"status": "ok"})

    result = _cold(handler, restart=restarted.append)
    assert restarted == ["box"]
    assert result.error == ""
    assert calls.count("/health") == 3
    assert calls.count("/api/chat") == 2
    assert result.health_ms <= result.ready_ms
    assert result.first.outcome == result.second.outcome == "ok"
    assert result.memory_after_mib == 350.0


def test_cold_start_reports_a_backend_that_never_comes_up() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    result = _cold(handler, timeout=0.3)
    assert result.error == "/health never answered"
    assert result.first is None


def test_cold_start_waits_for_readiness_too() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200 if request.url.path == "/health" else 503)

    result = _cold(handler, timeout=0.3)
    assert result.health_ms is not None
    assert result.error == "/health/ready never answered"
    assert result.first is None


def test_cold_start_reports_a_failed_restart() -> None:
    def restart(container: str) -> None:
        raise subprocess.CalledProcessError(1, "docker")

    result = _cold(lambda r: httpx.Response(200), restart=restart)
    assert result.error == "restart failed: CalledProcessError"


# --- reports and CLI ----------------------------------------------------------------------


def _summary(**overrides: object) -> dict:
    base = {
        "users": 5,
        "requests": 40,
        "ok": 40,
        "outcomes": {"ok": 40},
        "throughput_per_minute": 82.7,
        "first_event_ms": {"p50": 611, "p95": 666, "max": 700},
        "first_token_ms": {"p50": 1071, "p95": 8384, "max": 9000},
        "done_ms": {"p50": 1629, "p95": 8878, "max": 9556},
        "retrieval_ms": {"p50": 6504, "p95": 8017},
        "peak_memory_mib": 444.3,
        "memory_limit_mib": 768,
        "peak_cpu_percent": 102.1,
        "errors": [],
    }
    base.update(overrides)
    return base


def test_render_load() -> None:
    report = render_load(
        [
            _summary(),
            _summary(
                users=40,
                ok=39,
                outcomes={"ok": 39, "network": 1},
                errors=["ReadTimeout"],
                peak_memory_mib=None,
                peak_cpu_percent=None,
            ),
        ]
    )
    assert (
        "| 5 | 40/40 | 82.7 | 611 / 666 | 1,071 / 8,384 | 1,629 / 8,878 / 9,556 "
        "| 6,504 / 8,017 | 444.3 / 768 MiB | 102.1% |" in report
    )
    assert "| 40 | 39/40 |" in report and "| – | – |" in report
    assert "- 40 users: ok: 39, network: 1" in report
    assert "  - ReadTimeout" in report


def test_render_coldstart() -> None:
    first = {
        "outcome": "ok",
        "first_token_ms": 2434,
        "done_ms": 2872,
        "tool_ms": {"search_f1_knowledge": 1367},
    }
    second = {"outcome": "answer_error", "error": "boom", "done_ms": 900, "tool_ms": {}}
    report = render_coldstart(
        [
            {
                "health_ms": 1079,
                "ready_ms": 1086,
                "first": first,
                "second": second,
                "memory_after_mib": 345.6,
                "error": "",
            },
            {
                "health_ms": None,
                "ready_ms": None,
                "first": None,
                "second": None,
                "memory_after_mib": None,
                "error": "/health never answered",
            },
        ]
    )
    assert (
        "| 1 | 1,079 | 1,086 | 2,434 / 2,872 | 1,367 | 900 | – | 345.6 MiB |" in report
    )
    assert "- run 2: /health never answered" in report
    assert "- run 1: second answer: answer_error boom" in report


@pytest.mark.parametrize(
    "argv",
    [
        ["load", "--users", "0"],
        ["load", "--users", "a,b"],
        ["load", "--users", ""],
        ["load", "--requests", "0"],
        ["coldstart", "--runs", "11"],
        ["nope"],
    ],
)
def test_cli_rejects_bad_arguments(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as info:
        cli.main(argv)
    assert info.value.code == 2


def test_question_sets() -> None:
    asked = cli.questions()
    knowledge = cli.knowledge_questions()
    assert len(asked) > 80 and len(set(asked)) == len(asked)
    assert knowledge and set(knowledge) <= set(asked)
    assert "Explain Abu Dhabi 2021" in knowledge
    assert not any("most" in q.lower().split() for q in knowledge)
