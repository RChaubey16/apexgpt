"""The production smoke test (F7.4), against an in-process fake site."""

import json

import httpx
import pytest

from evals import __main__ as cli
from evals.golden import GoldenSetError
from evals.smoke import (
    FOREIGN_ORIGIN,
    ask,
    events,
    infra_checks,
    observe,
    render,
    run_smoke,
)
from tests.evals.fakes import question

FRONTEND = "https://apexgpt.example"
API = "https://api.apexgpt.example"


def sse(*items: tuple[str, object]) -> str:
    return "".join(f"event: {n}\ndata: {json.dumps(d)}\n\n" for n, d in items)


ANSWER = sse(
    ("tool", {"name": "query_stats", "status": "started"}),
    ("tool", {"name": "query_stats", "status": "finished", "ok": True}),
    ("token", {"text": "Lewis Hamilton has "}),
    ("citation", {"id": "S1", "title": "Lewis Hamilton", "url": "u"}),
    ("citation", {"id": "S2", "title": "Lewis Hamilton", "url": "u"}),
    ("token", {"text": "105 wins [S1]."}),
    (
        "done",
        {
            "question": "Who has won the most?",
            "provider": "groq",
            "model": "m",
            "tools": [{"name": "query_stats", "ok": True}],
            "latency_ms": 900,
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "cached": True,
        },
    ),
)

STATS_Q = question(
    id="stats-a",
    category="stats",
    question="Who has won the most?",
    expect={"answer": ["Lewis Hamilton", "105"], "tools": ["query_stats"]},
    sql="SELECT 'Lewis Hamilton', 105",
)


def test_events_parse_frames_and_odd_data() -> None:
    lines = [
        "event: a",
        'data: {"x": 1}',
        "",
        "event: b",
        "data: not json",
        "",
        "event: c",
        "data: [1]",
    ]
    assert events(lines) == [
        ("a", {"x": 1}),
        ("b", {"raw": "not json"}),
        ("c", {"raw": "[1]"}),
    ]


def test_observe_builds_what_scoring_needs() -> None:
    result = observe(events(ANSWER.split("\n")), "Who has won the most?")
    obs = result.observed
    assert obs.text == "Lewis Hamilton has 105 wins [S1]."
    assert obs.cited_titles == ("Lewis Hamilton",)
    assert [(t.name, t.ok) for t in obs.tools] == [("query_stats", True)]
    assert (obs.provider, obs.latency_ms) == ("groq", 900)
    assert result.cached is True and result.error == ""


def test_observe_uses_the_rewritten_question_and_reports_errors() -> None:
    stream = events(
        sse(
            ("question", {"text": "Who was Verstappen's team-mate in 2021?"}),
            ("done", {}),
        ).split("\n")
    )
    assert observe(stream, "Who was his team-mate?").observed.standalone == (
        "Who was Verstappen's team-mate in 2021?"
    )
    failed = observe(events(sse(("error", {"message": "No model"})).split("\n")), "q")
    assert failed.observed is None and failed.error == "answer error: No model"
    cut = observe(events(sse(("token", {"text": "x"})).split("\n")), "q")
    assert cut.error == "the stream ended without done or error"


def _client(handler) -> httpx.Client:  # noqa: ANN001
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_ask_sends_question_and_history() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, text=ANSWER)

    q = question(
        category="follow_up",
        question="And his wins?",
        history=[{"role": "user", "content": "Who is Lewis Hamilton?"}],
        expect={"answer": ["105"]},
    )
    result = ask(_client(handler), API, q)
    assert seen["path"] == "/api/chat"
    assert seen["body"]["history"] == [
        {"role": "user", "content": "Who is Lewis Hamilton?"}
    ]
    assert result.status == 200 and result.observed is not None


@pytest.mark.parametrize(
    ("respond", "error"),
    [
        (lambda r: httpx.Response(429, json={"detail": "slow down"}), "HTTP 429"),
        (
            lambda r: (_ for _ in ()).throw(httpx.ConnectError("x")),
            "network: ConnectError",
        ),
    ],
)
def test_ask_failures(respond, error: str) -> None:  # noqa: ANN001
    assert error in ask(_client(respond), API, STATS_Q).error


SEASON = {
    "season": 2026, "round": 21, "total_rounds": 23, "complete": False,
    "drivers": [{"position": 1, "family_name": "Antonelli"}],
    "constructors": [{"position": 1, "name": "Mercedes"}],
    "next_race": {"name": "Qatar Grand Prix"}, "stale": False,
}  # fmt: skip


def site(**overrides):  # noqa: ANN003, ANN201
    """A fake production site; overrides replace a path's response."""

    def handler(request: httpx.Request) -> httpx.Response:
        key = f"{request.method} {request.url.host}{request.url.path}"
        if key in overrides:
            return overrides[key](request)
        api_host, fe_host = "api.apexgpt.example", "apexgpt.example"
        if request.url.host == api_host:
            if request.url.path == "/health":
                return httpx.Response(
                    200, json={"status": "ok", "environment": "production"}
                )
            if request.url.path == "/health/ready":
                return httpx.Response(200, json={"status": "ok", "database": "ok"})
            if request.method == "OPTIONS":
                origin = request.headers["origin"]
                if origin == FRONTEND:
                    return httpx.Response(
                        200, headers={"access-control-allow-origin": FRONTEND}
                    )
                return httpx.Response(400)
            if request.url.path == "/api/chat":
                return httpx.Response(200, text=ANSWER)
            if request.url.path == "/api/season/current":
                return httpx.Response(200, json=SEASON)
            return httpx.Response(404)
        if request.url.host == fe_host:
            if request.url.path == "/api/health":
                return httpx.Response(200, json={"status": "ok"})
            return httpx.Response(
                200, text="<!DOCTYPE html><html><body>ApexGPT</body></html>"
            )
        return httpx.Response(404)

    return _client(handler)


def test_infra_checks_pass_on_a_healthy_site() -> None:
    clock = iter([10.0, 10.5])
    checks, ready = infra_checks(site(), FRONTEND, API, clock=lambda: next(clock))
    assert [c.name for c in checks][0] == "backend /health/ready"  # first: wakes Neon
    assert all(c.ok for c in checks), [c for c in checks if not c.ok]
    assert ready == 0.5
    assert len(checks) == 8
    season = next(c for c in checks if c.name == "backend /api/season/current")
    assert season.detail == (
        "HTTP 200, 2026 after round 21, next Qatar Grand Prix, stale False"
    )


@pytest.mark.parametrize(
    ("override", "failing"),
    [
        (
            {
                "GET api.apexgpt.example/health": lambda r: httpx.Response(
                    200, json={"status": "ok", "environment": "development"}
                )
            },
            "backend /health",
        ),
        (
            {
                "GET api.apexgpt.example/health/ready": lambda r: httpx.Response(
                    503, json={"database": "unavailable"}
                )
            },
            "backend /health/ready",
        ),
        (
            {"GET api.apexgpt.example/docs": lambda r: httpx.Response(200)},
            "API docs hidden",
        ),
        (
            {
                "OPTIONS api.apexgpt.example/api/chat": lambda r: httpx.Response(
                    200, headers={"access-control-allow-origin": "*"}
                )
            },
            "CORS allows the frontend",
        ),
        (
            {
                "GET api.apexgpt.example/api/season/current": lambda r: httpx.Response(
                    503, json={"detail": "unavailable"}
                )
            },
            "backend /api/season/current",
        ),
        (
            {
                "GET api.apexgpt.example/api/season/current": lambda r: httpx.Response(
                    200, json={**SEASON, "stale": True}
                )
            },
            "backend /api/season/current",
        ),
        (
            {
                "GET api.apexgpt.example/api/season/current": lambda r: httpx.Response(
                    200, json={**SEASON, "drivers": []}
                )
            },
            "backend /api/season/current",
        ),
        (
            {"GET apexgpt.example/api/health": lambda r: httpx.Response(502)},
            "frontend /api/health",
        ),
        (
            {
                "GET apexgpt.example/": lambda r: (_ for _ in ()).throw(
                    httpx.ConnectError("x")
                )
            },
            "frontend page",
        ),
    ],
)
def test_infra_failures_are_named(override: dict, failing: str) -> None:
    checks, _ = infra_checks(site(**override), FRONTEND, API)
    assert [c.name for c in checks if not c.ok][:1] == [failing]


def test_cors_must_refuse_a_foreign_origin() -> None:
    def allow_all(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"access-control-allow-origin": request.headers["origin"]}
        )

    checks, _ = infra_checks(
        site(**{"OPTIONS api.apexgpt.example/api/chat": allow_all}), FRONTEND, API
    )
    refused = next(c for c in checks if c.name == "CORS refuses other origins")
    assert not refused.ok and FOREIGN_ORIGIN in refused.detail


def test_a_whole_run_paces_questions_and_scores_them() -> None:
    waits: list[float] = []
    lines: list[str] = []
    wrong = question(
        id="stats-b",
        category="stats",
        question="Most poles?",
        expect={"answer": ["104"], "tools": ["query_stats"]},
        sql="SELECT 104",
    )
    report = run_smoke(
        FRONTEND + "/",
        API + "/",
        [STATS_Q, wrong],
        delay=11,
        client=site(),
        sleep=waits.append,
        progress=lines.append,
    )
    assert waits == [11]
    assert [q.ok for q in report.questions] == [True, False]
    assert not report.ok
    assert any("FAIL stats-b" in line and "(cached)" in line for line in lines)

    text = render(report, "2026-11-26T10:00:00+00:00")
    assert "**FAIL**: infrastructure 8/8, answers 1/2" in text
    assert "| `stats-a` | ok |" in text
    assert "answer: missing ['104']" in text
    assert "## Failed answers" in text
    assert "- `stats-b`: Most poles?" in text
    assert "  > Lewis Hamilton has 105 wins [S1]." in text
    assert "First /health/ready:" in text


def test_an_answer_error_fails_the_run() -> None:
    """No `done` means nothing to score; that must not count as a pass."""
    failing = site(
        **{
            "POST api.apexgpt.example/api/chat": lambda r: httpx.Response(
                200, text=sse(("error", {"message": "No language model is available"}))
            )
        }
    )
    report = run_smoke(
        FRONTEND,
        API,
        [STATS_Q],
        client=failing,
        sleep=pytest.fail,
        progress=lambda _: None,
    )
    [outcome] = report.questions
    assert outcome.checks == [] and not outcome.ok
    assert not report.ok
    assert "answer error: No language model" in render(report, "t")


def test_a_healthy_run_passes() -> None:
    report = run_smoke(
        FRONTEND,
        API,
        [STATS_Q],
        client=site(),
        sleep=pytest.fail,
        progress=lambda _: None,
    )
    assert report.ok


def test_smoke_questions_need_deterministic_checks() -> None:
    with pytest.raises(GoldenSetError, match="deterministic checks"):
        question(smoke=True, expect={"facts": ["only for the judge"]})
    with pytest.raises(GoldenSetError, match="deterministic checks"):
        question(smoke=True, category="out_of_scope", expect={"behavior": "decline"})
    assert question(smoke=True).smoke


def test_the_golden_set_has_a_useful_smoke_subset() -> None:
    from evals.golden import load_golden_set

    smoke = [q for q in load_golden_set().questions if q.smoke]
    assert 6 <= len(smoke) <= 12  # under the per-IP limit in ~2 minutes
    assert any(q.history for q in smoke)  # a follow-up
    assert any(q.expect.sources for q in smoke)  # a cited answer
    assert any("query_stats" in q.expect.tools for q in smoke)


@pytest.mark.parametrize(
    "url", ["ftp://x", "apexgpt.example", "https://user:pw@x.example"]
)
def test_cli_refuses_bad_urls(url: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["smoke", "--frontend", url, "--api", API]) == 2
    assert "not an http(s) URL" in capsys.readouterr().err


def test_cli_smoke_with_a_fake_site(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:  # noqa: ANN001
    import evals.smoke as smoke_module

    monkeypatch.setattr(cli, "SMOKE_DIR", tmp_path)
    real = smoke_module.run_smoke
    monkeypatch.setattr(
        smoke_module,
        "run_smoke",
        lambda f, a, qs, delay: real(f, a, qs[:1], delay=0, client=site()),
    )
    assert cli.main(["smoke", "--frontend", FRONTEND, "--api", API]) == 0
    [report] = tmp_path.glob("*.md")
    assert "**PASS**" in report.read_text()


def test_cli_smoke_exits_1_when_something_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path  # noqa: ANN001
) -> None:
    import evals.smoke as smoke_module

    monkeypatch.setattr(cli, "SMOKE_DIR", tmp_path)
    real = smoke_module.run_smoke
    broken = site(**{"GET api.apexgpt.example/docs": lambda r: httpx.Response(200)})
    monkeypatch.setattr(
        smoke_module,
        "run_smoke",
        lambda f, a, qs, delay: real(f, a, qs[:1], delay=0, client=broken),
    )
    assert cli.main(["smoke", "--frontend", FRONTEND, "--api", API]) == 1
    [report] = tmp_path.glob("*.md")
    assert "**FAIL**" in report.read_text()


def test_unknown_question_ids_are_refused(capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        cli.main(["smoke", "--frontend", FRONTEND, "--api", API, "--id", "nope"]) == 2
    )
    assert "unknown question ids: nope" in capsys.readouterr().err
