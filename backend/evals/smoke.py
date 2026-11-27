"""Production smoke test (F7.4): the live site, over HTTP, like a browser.

    uv run python -m evals smoke --frontend https://apexgpt.ruturaj.xyz \
                                 --api https://apexgpt-api.ruturaj.xyz

1. Infrastructure: the frontend page and its /api/health; the backend's
   /health (environment production), /health/ready (and its latency: the first
   call after 5+ idle minutes includes Neon waking up), /docs hidden, and CORS
   allowing the frontend's origin and nothing else, and /api/season/current
   (F8.3) serving fresh standings from Jolpica.
2. Answers: the golden questions marked `smoke: true`, asked through
   POST /api/chat and scored with the deterministic checks (answer values,
   tools, sources, follow-up rewrites). No LLM judge: the result is repeatable
   and costs only the answers.

Questions are spaced (default 11 s) to stay under the per-IP limit of 6 answers
a minute. Answers repeated within 24 hours come from the production cache,
which the report shows. Exit code 1 when anything fails.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

import httpx

from evals.golden import GoldenQuestion
from evals.scoring import CheckResult, Observed, Status, ToolUse, check_answer

TIMEOUT_SECONDS = 120.0
DEFAULT_DELAY = 11.0  # 6 answers/minute per IP in production
FOREIGN_ORIGIN = "https://smoke-test.invalid"
EXCERPT_CHARS = 400


# --- the chat stream -----------------------------------------------------------


@dataclass
class StreamResult:
    status: int | None = None
    observed: Observed | None = None
    cached: bool = False
    error: str = ""
    seconds: float = 0.0


def events(lines: Iterable[str]) -> list[tuple[str, dict]]:
    """(event, data) pairs from SSE lines; data that isn't a JSON object is
    kept as {"raw": text}."""
    out: list[tuple[str, dict]] = []
    name, data = None, []

    def flush() -> None:
        if name is None:
            return
        text = "\n".join(data)
        try:
            value = json.loads(text) if text else {}
        except ValueError:
            value = {"raw": text}
        out.append((name, value if isinstance(value, dict) else {"raw": text}))

    for line in lines:
        if line == "":
            flush()
            name, data = None, []
        elif line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    flush()
    return out


def observe(stream: Sequence[tuple[str, dict]], asked: str) -> StreamResult:
    """What one answer's events say; an `error` event or no `done` is an error."""
    text, titles, standalone = [], [], asked
    for name, data in stream:
        if name == "token":
            text.append(str(data.get("text", "")))
        elif name == "citation":
            title = data.get("title")
            if isinstance(title, str) and title not in titles:
                titles.append(title)
        elif name == "question":
            standalone = str(data.get("text") or standalone)
        elif name == "error":
            return StreamResult(error=f"answer error: {data.get('message', '')}"[:300])
        elif name == "done":
            tools = tuple(
                ToolUse(name=str(t.get("name")), ok=bool(t.get("ok")))
                for t in data.get("tools") or []
                if isinstance(t, dict)
            )
            observed = Observed(
                standalone=str(data.get("question") or standalone),
                text="".join(text),
                tools=tools,
                cited_titles=tuple(titles),
                provider=str(data.get("provider") or ""),
                model=str(data.get("model") or ""),
                prompt_tokens=int(data.get("prompt_tokens") or 0),
                completion_tokens=int(data.get("completion_tokens") or 0),
                latency_ms=int(data.get("latency_ms") or 0),
            )
            return StreamResult(observed=observed, cached=bool(data.get("cached")))
    return StreamResult(error="the stream ended without done or error")


def ask(
    client: httpx.Client,
    api: str,
    question: GoldenQuestion,
    clock: Callable[[], float] = time.perf_counter,
) -> StreamResult:
    body = {
        "question": question.question,
        "history": [{"role": m.role, "content": m.content} for m in question.history],
    }
    started = clock()
    try:
        with client.stream("POST", f"{api}/api/chat", json=body) as response:
            if response.status_code != 200:
                detail = response.read().decode(errors="replace")[:200]
                result = StreamResult(error=f"HTTP {response.status_code}: {detail}")
            else:
                result = observe(events(response.iter_lines()), question.question)
            result.status = response.status_code
    except httpx.HTTPError as exc:
        result = StreamResult(error=f"network: {type(exc).__name__}")
    result.seconds = round(clock() - started, 1)
    return result


# --- infrastructure ---------------------------------------------------------------


@dataclass
class InfraCheck:
    name: str
    ok: bool
    detail: str = ""


def _json(response: httpx.Response) -> dict:
    try:
        value = response.json()
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def infra_checks(
    client: httpx.Client,
    frontend: str,
    api: str,
    clock: Callable[[], float] = time.perf_counter,
) -> tuple[list[InfraCheck], float | None]:
    """The checks, and /health/ready's seconds on this (first) call."""
    checks: list[InfraCheck] = []

    def check(name: str, run: Callable[[], InfraCheck]) -> None:
        try:
            checks.append(run())
        except httpx.HTTPError as exc:
            checks.append(InfraCheck(name, False, f"network: {type(exc).__name__}"))

    ready_seconds: float | None = None

    def ready() -> InfraCheck:
        nonlocal ready_seconds
        started = clock()
        r = client.get(f"{api}/health/ready")
        ready_seconds = round(clock() - started, 2)
        ok = r.status_code == 200 and _json(r).get("database") == "ok"
        return InfraCheck(
            "backend /health/ready", ok, f"HTTP {r.status_code} in {ready_seconds} s"
        )

    # Readiness first: after idle minutes it is the call that wakes Neon.
    check("backend /health/ready", ready)

    def health() -> InfraCheck:
        r = client.get(f"{api}/health")
        env = _json(r).get("environment")
        return InfraCheck(
            "backend /health",
            r.status_code == 200 and env == "production",
            f"HTTP {r.status_code}, environment {env}",
        )

    def docs() -> InfraCheck:
        r = client.get(f"{api}/docs")
        return InfraCheck(
            "API docs hidden", r.status_code == 404, f"HTTP {r.status_code}"
        )

    def preflight(origin: str) -> httpx.Response:
        return client.options(
            f"{api}/api/chat",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

    def cors_allowed() -> InfraCheck:
        r = preflight(frontend)
        allowed = r.headers.get("access-control-allow-origin")
        return InfraCheck(
            "CORS allows the frontend",
            r.status_code == 200 and allowed == frontend,
            f"HTTP {r.status_code}, allow-origin {allowed}",
        )

    def cors_refused() -> InfraCheck:
        r = preflight(FOREIGN_ORIGIN)
        allowed = r.headers.get("access-control-allow-origin")
        return InfraCheck(
            "CORS refuses other origins",
            allowed is None,
            f"HTTP {r.status_code}, allow-origin {allowed}",
        )

    def season() -> InfraCheck:
        r = client.get(f"{api}/api/season/current")
        body = _json(r)
        drivers, stale = body.get("drivers"), body.get("stale")
        ok = (
            r.status_code == 200
            and isinstance(body.get("season"), int)
            and isinstance(drivers, list)
            and len(drivers) > 0
            and isinstance(body.get("constructors"), list)
            and stale is False
        )
        if r.status_code != 200:
            detail = f"HTTP {r.status_code}"
        else:
            race = body.get("next_race") or {}
            detail = (
                f"HTTP 200, {body.get('season')} after round {body.get('round')}, "
                f"next {race.get('name', 'none')}, stale {stale}"
            )
        return InfraCheck("backend /api/season/current", ok, detail)

    def page() -> InfraCheck:
        r = client.get(f"{frontend}/")
        return InfraCheck(
            "frontend page",
            r.status_code == 200 and "<html" in r.text.lower(),
            f"HTTP {r.status_code}",
        )

    def frontend_health() -> InfraCheck:
        r = client.get(f"{frontend}/api/health")
        return InfraCheck(
            "frontend /api/health",
            r.status_code == 200 and _json(r).get("status") == "ok",
            f"HTTP {r.status_code}",
        )

    for name, run in (
        ("backend /health", health),
        ("API docs hidden", docs),
        ("CORS allows the frontend", cors_allowed),
        ("CORS refuses other origins", cors_refused),
        ("backend /api/season/current", season),
        ("frontend page", page),
        ("frontend /api/health", frontend_health),
    ):
        check(name, run)
    return checks, ready_seconds


# --- the whole run -------------------------------------------------------------------


@dataclass
class QuestionOutcome:
    question: GoldenQuestion
    result: StreamResult
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.result.error and all(
            c.status is Status.PASS for c in self.checks
        )


@dataclass
class SmokeReport:
    frontend: str
    api: str
    infra: list[InfraCheck]
    ready_seconds: float | None
    questions: list[QuestionOutcome]

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.infra) and all(q.ok for q in self.questions)


def run_smoke(
    frontend: str,
    api: str,
    questions: Sequence[GoldenQuestion],
    *,
    delay: float = DEFAULT_DELAY,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
    progress: Callable[[str], None] = print,
) -> SmokeReport:
    frontend, api = frontend.rstrip("/"), api.rstrip("/")
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False)
    try:
        infra, ready = infra_checks(client, frontend, api)
        for c in infra:
            progress(f"{'ok  ' if c.ok else 'FAIL'} {c.name}: {c.detail}")
        outcomes = []
        for index, question in enumerate(questions, 1):
            if index > 1 and delay:
                sleep(delay)
            result = ask(client, api, question)
            checks = check_answer(question, result.observed) if result.observed else []
            outcome = QuestionOutcome(question, result, checks)
            outcomes.append(outcome)
            failed = [c.name for c in checks if c.status is not Status.PASS]
            note = result.error or ", ".join(failed)
            cached = " (cached)" if result.cached else ""
            progress(
                f"[{index}/{len(questions)}] {'ok  ' if outcome.ok else 'FAIL'} "
                f"{question.id} {result.seconds} s{cached}"
                + (f"  ({note})" if note else "")
            )
    finally:
        if own:
            client.close()
    return SmokeReport(frontend, api, infra, ready, outcomes)


def render(report: SmokeReport, started_at: str) -> str:
    q_ok = sum(q.ok for q in report.questions)
    i_ok = sum(c.ok for c in report.infra)
    lines = [
        "# ApexGPT production smoke test",
        "",
        f"- When: {started_at}",
        f"- Frontend: {report.frontend}",
        f"- Backend: {report.api}",
        f"- First /health/ready: {report.ready_seconds} s "
        "(includes Neon waking up when it had suspended)",
        "",
        f"**{'PASS' if report.ok else 'FAIL'}**: infrastructure {i_ok}/{len(report.infra)}, "
        f"answers {q_ok}/{len(report.questions)}",
        "",
        "## Infrastructure",
        "",
        "| Check | Result | Detail |",
        "|---|---|---|",
    ]
    lines += [
        f"| {c.name} | {'ok' if c.ok else 'FAIL'} | {c.detail} |" for c in report.infra
    ]
    lines += [
        "",
        "## Answers",
        "",
        "| Question | Result | Seconds | Cached | Provider | Failed checks |",
        "|---|---|---:|---|---|---|",
    ]
    for q in report.questions:
        r = q.result
        failed = r.error or "; ".join(
            f"{c.name}: {c.detail}" for c in q.checks if c.status is not Status.PASS
        )
        provider = r.observed.provider if r.observed else "–"
        lines.append(
            f"| `{q.question.id}` | {'ok' if q.ok else 'FAIL'} | {r.seconds} "
            f"| {'yes' if r.cached else 'no'} | {provider} | {failed.replace('|', '/')} |"
        )
    failed = [q for q in report.questions if not q.ok and q.result.observed]
    if failed:
        lines += ["", "## Failed answers", ""]
        for q in failed:
            text = " ".join(q.result.observed.text.split())
            if len(text) > EXCERPT_CHARS:
                text = text[:EXCERPT_CHARS].rsplit(" ", 1)[0] + " …"
            lines += [f"- `{q.question.id}`: {q.question.question}", f"  > {text}"]
    return "\n".join(lines) + "\n"
