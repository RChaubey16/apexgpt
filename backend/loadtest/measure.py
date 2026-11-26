"""Load and cold-start measurements against a running backend (F6.4).

Requests go to POST /api/chat like the frontend's (SSE), so the times are what
a user sees: the first event, the first answer token and the end of the
answer. Container memory and CPU come from ``docker stats`` while it runs.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import re
import subprocess
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field

import httpx

CHAT_PATH = "/api/chat"
REQUEST_TIMEOUT_SECONDS = 180.0


# --- one request --------------------------------------------------------------


@dataclass
class RequestResult:
    question: str
    status: int | None = None  # HTTP status; None when it never connected
    outcome: str = "ok"  # ok | http_error | answer_error | no_done | network
    error: str = ""
    first_event_ms: int | None = None
    first_token_ms: int | None = None
    done_ms: int | None = None
    # Seconds between a tool's started and finished events, by tool name.
    tool_ms: dict[str, int] = field(default_factory=dict)


async def ask(
    client: httpx.AsyncClient,
    base_url: str,
    question: str,
    clock: Callable[[], float] = time.perf_counter,
) -> RequestResult:
    """One chat request, timed from sending it."""
    result = RequestResult(question=question)
    started = clock()
    tool_started: dict[str, float] = {}

    def elapsed() -> int:
        return round((clock() - started) * 1000)

    try:
        async with client.stream(
            "POST", base_url.rstrip("/") + CHAT_PATH, json={"question": question}
        ) as response:
            result.status = response.status_code
            if response.status_code != 200:
                body = (await response.aread()).decode(errors="replace")
                result.outcome = "http_error"
                result.error = f"HTTP {response.status_code}: {body[:200]}"
                return result
            name = None
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    name = line[6:].strip()
                    if result.first_event_ms is None:
                        result.first_event_ms = elapsed()
                elif line.startswith("data:") and name is not None:
                    data = line[5:].strip()
                    if name == "token" and result.first_token_ms is None:
                        result.first_token_ms = elapsed()
                    elif name == "tool":
                        _tool_timing(data, tool_started, result, clock, started)
                    elif name == "done":
                        result.done_ms = elapsed()
                    elif name == "error":
                        result.outcome = "answer_error"
                        result.error = _message(data)
                        result.done_ms = elapsed()
    except httpx.HTTPError as exc:
        result.outcome = "network"
        result.error = type(exc).__name__
        return result
    if result.outcome == "ok" and result.done_ms is None:
        result.outcome = "no_done"
        result.error = "the stream ended without done or error"
    return result


def _message(data: str) -> str:
    try:
        return str(json.loads(data).get("message", ""))[:200]
    except (ValueError, AttributeError):
        return data[:200]


def _tool_timing(
    data: str,
    started_at: dict[str, float],
    result: RequestResult,
    clock: Callable[[], float],
    t0: float,
) -> None:
    try:
        event = json.loads(data)
        name, status = event["name"], event["status"]
    except (ValueError, KeyError, TypeError):
        return
    now = clock()
    if status == "started":
        started_at[name] = now
    elif status == "finished" and name in started_at:
        result.tool_ms[name] = result.tool_ms.get(name, 0) + round(
            (now - started_at.pop(name)) * 1000
        )


# --- container stats ----------------------------------------------------------

_SIZE = re.compile(r"^\s*([\d.]+)\s*([KMGT]?i?B)\s*$", re.IGNORECASE)
_UNITS = {
    "b": 1 / 2**20,
    "kib": 1 / 1024,
    "kb": 1000 / 2**20,
    "mib": 1.0,
    "mb": 10**6 / 2**20,
    "gib": 1024.0,
    "gb": 10**9 / 2**20,
}


def mib(text: str) -> float:
    """A docker size ("412.3MiB", "1.2GiB", "768MB") in MiB."""
    match = _SIZE.match(text)
    if not match:
        raise ValueError(f"not a size: {text!r}")
    number, unit = float(match.group(1)), match.group(2).lower()
    if unit not in _UNITS:
        raise ValueError(f"unknown unit in {text!r}")
    return number * _UNITS[unit]


@dataclass(frozen=True)
class Sample:
    memory_mib: float
    limit_mib: float
    cpu_percent: float


def parse_stats(line: str) -> Sample:
    """One ``docker stats --format '{{.MemUsage}}|{{.CPUPerc}}'`` line."""
    usage, cpu = line.strip().split("|")
    used, limit = (part.strip() for part in usage.split("/"))
    return Sample(mib(used), mib(limit), float(cpu.strip().rstrip("%")))


def docker_stats(container: str) -> Sample | None:
    try:
        out = subprocess.run(  # noqa: S603 (fixed arguments)
            [  # noqa: S607 (docker on PATH)
                "docker",
                "stats",
                "--no-stream",
                "--format",
                "{{.MemUsage}}|{{.CPUPerc}}",
                container,
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        return parse_stats(out.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


class StatsSampler:
    """Samples a container's memory and CPU in the background."""

    def __init__(
        self,
        container: str | None,
        interval: float = 1.0,
        read: Callable[[str], Sample | None] = docker_stats,
    ) -> None:
        self.container = container
        self.interval = interval
        self.samples: list[Sample] = []
        self._read = read
        self._task: asyncio.Task | None = None

    async def _loop(self) -> None:
        while True:
            sample = await asyncio.to_thread(self._read, self.container)
            if sample is not None:
                self.samples.append(sample)
            await asyncio.sleep(self.interval)

    async def __aenter__(self) -> StatsSampler:
        if self.container:
            self._task = asyncio.create_task(self._loop())
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task


# --- a load scenario ------------------------------------------------------------


def percentile(values: Sequence[int], p: float) -> int | None:
    """Nearest-rank percentile; None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(1, math.ceil(p / 100 * len(ordered))) - 1]


@dataclass
class Scenario:
    users: int
    requests: int
    wall_seconds: float
    results: list[RequestResult]
    samples: list[Sample]

    def summary(self) -> dict[str, object]:
        ok = [r for r in self.results if r.outcome == "ok"]

        def stat(attr: str) -> dict[str, int | None]:
            values = [getattr(r, attr) for r in ok if getattr(r, attr) is not None]
            return {
                "p50": percentile(values, 50),
                "p95": percentile(values, 95),
                "max": max(values) if values else None,
            }

        retrieval = [
            r.tool_ms["search_f1_knowledge"]
            for r in ok
            if "search_f1_knowledge" in r.tool_ms
        ]
        return {
            "users": self.users,
            "requests": self.requests,
            "ok": len(ok),
            "outcomes": dict(Counter(r.outcome for r in self.results)),
            "throughput_per_minute": (
                round(len(ok) / self.wall_seconds * 60, 1) if self.wall_seconds else 0.0
            ),
            "first_event_ms": stat("first_event_ms"),
            "first_token_ms": stat("first_token_ms"),
            "done_ms": stat("done_ms"),
            "retrieval_ms": {
                "p50": percentile(retrieval, 50),
                "p95": percentile(retrieval, 95),
            },
            "peak_memory_mib": (
                round(max(s.memory_mib for s in self.samples), 1)
                if self.samples
                else None
            ),
            "memory_limit_mib": (
                round(self.samples[0].limit_mib) if self.samples else None
            ),
            "peak_cpu_percent": (
                round(max(s.cpu_percent for s in self.samples), 1)
                if self.samples
                else None
            ),
            "errors": sorted({r.error for r in self.results if r.error})[:5],
        }


async def run_scenario(
    base_url: str,
    questions: Sequence[str],
    users: int,
    requests: int,
    container: str | None = None,
    *,
    client: httpx.AsyncClient | None = None,
    clock: Callable[[], float] = time.perf_counter,
) -> Scenario:
    """``requests`` questions asked by ``users`` concurrent users, each asking
    the next question as soon as its last answer ends."""
    if users < 1 or requests < 1:
        raise ValueError("users and requests must be at least 1")
    if not questions:
        raise ValueError("no questions to ask")
    queue: asyncio.Queue[str] = asyncio.Queue()
    for i in range(requests):
        queue.put_nowait(questions[i % len(questions)])
    results: list[RequestResult] = []
    own = client is None
    client = client or httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT_SECONDS,
        limits=httpx.Limits(max_connections=users, max_keepalive_connections=users),
    )

    async def user() -> None:
        while True:
            try:
                question = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            results.append(await ask(client, base_url, question, clock))

    started = clock()
    try:
        async with StatsSampler(container) as sampler:
            await asyncio.gather(*(user() for _ in range(users)))
    finally:
        if own:
            await client.aclose()
    return Scenario(users, requests, clock() - started, results, sampler.samples)


# --- cold start -------------------------------------------------------------------


@dataclass
class ColdStart:
    restart_ms: int | None = None  # `docker restart` returned
    health_ms: int | None = None  # first 200 from /health
    ready_ms: int | None = None  # first 200 from /health/ready
    first: RequestResult | None = None
    second: RequestResult | None = None
    memory_after_mib: float | None = None
    error: str = ""

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


async def wait_for(
    client: httpx.AsyncClient,
    url: str,
    timeout: float,
    clock: Callable[[], float] = time.perf_counter,
    interval: float = 0.1,
) -> bool:
    deadline = clock() + timeout
    while clock() < deadline:
        try:
            if (await client.get(url, timeout=2.0)).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        await asyncio.sleep(interval)
    return False


def restart_container(container: str) -> None:
    subprocess.run(  # noqa: S603
        ["docker", "restart", container],  # noqa: S607 (docker on PATH)
        capture_output=True,
        timeout=120,
        check=True,
    )


async def cold_start(
    base_url: str,
    container: str,
    questions: tuple[str, str],
    *,
    timeout: float = 120.0,
    restart: Callable[[str], None] = restart_container,
    read_stats: Callable[[str], Sample | None] = docker_stats,
    clock: Callable[[], float] = time.perf_counter,
) -> ColdStart:
    """Restart the container, then time health, readiness and two answers."""
    result = ColdStart()
    base = base_url.rstrip("/")
    started = clock()

    def elapsed() -> int:
        return round((clock() - started) * 1000)

    try:
        await asyncio.to_thread(restart, container)
    except (OSError, subprocess.SubprocessError) as exc:
        result.error = f"restart failed: {type(exc).__name__}"
        return result
    result.restart_ms = elapsed()
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        if not await wait_for(client, base + "/health", timeout, clock):
            result.error = "/health never answered"
            return result
        result.health_ms = elapsed()
        if not await wait_for(client, base + "/health/ready", timeout, clock):
            result.error = "/health/ready never answered"
            return result
        result.ready_ms = elapsed()
        result.first = await ask(client, base, questions[0], clock)
        result.second = await ask(client, base, questions[1], clock)
    sample = await asyncio.to_thread(read_stats, container)
    result.memory_after_mib = round(sample.memory_mib, 1) if sample else None
    return result
