"""Load and cold-start tests against a running backend (F6.4).

Start the stub LLM and the backend's production image under its memory cap
(see backend/loadtest/README.md), then:

    uv run python -m loadtest load --users 1,2,5,10 --requests 20
    uv run python -m loadtest coldstart --runs 3

Results (JSON and markdown) go to data/loadtest/<UTC time>/ (git-ignored).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from evals.golden import load_golden_set
from loadtest.measure import cold_start, run_scenario
from loadtest.report import render_coldstart, render_load

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "data" / "loadtest"
DEFAULT_URL = "http://127.0.0.1:8000"
DEFAULT_CONTAINER = "apexgpt-backend-1"


def _users(text: str) -> list[int]:
    try:
        values = [int(part) for part in text.split(",") if part.strip()]
    except ValueError:
        raise argparse.ArgumentTypeError("a comma-separated list of numbers") from None
    if not values or any(not 1 <= v <= 100 for v in values):
        raise argparse.ArgumentTypeError("each value must be between 1 and 100")
    return values


def _count(low: int, high: int):  # noqa: ANN202
    def parse(text: str) -> int:
        value = int(text)
        if not low <= value <= high:
            raise argparse.ArgumentTypeError(f"must be between {low} and {high}")
        return value

    return parse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m loadtest")
    parser.add_argument("--url", default=DEFAULT_URL, help="backend base URL")
    parser.add_argument("--container", default=DEFAULT_CONTAINER)
    commands = parser.add_subparsers(dest="command", required=True)

    load = commands.add_parser("load", help="concurrent users asking questions")
    load.add_argument("--users", type=_users, default=[1, 2, 5, 10])
    load.add_argument("--requests", type=_count(1, 1000), default=20)

    cold = commands.add_parser("coldstart", help="restart, then time the first answers")
    cold.add_argument("--runs", type=_count(1, 10), default=3)
    return parser


def questions() -> list[str]:
    """Standalone golden questions: different on every request, so nothing is
    served twice even if the answer cache were on."""
    return [q.question for q in load_golden_set().questions if not q.history]


def knowledge_questions() -> list[str]:
    """Questions the stub answers with the knowledge search, the path that
    loads both ONNX models on first use."""
    from loadtest.stub_llm import STATS_QUESTION

    return [
        q.question
        for q in load_golden_set().questions
        if not q.history
        and "search_f1_knowledge" in q.expect.tools
        and not STATS_QUESTION.search(q.question)
    ]


def _write(name: str, data: object, report: str) -> Path:
    out = OUT_DIR / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.json").write_text(json.dumps(data, indent=2) + "\n")
    (out / f"{name}.md").write_text(report)
    return out


async def _load(args: argparse.Namespace) -> int:
    asked = questions()
    summaries = []
    for users in args.users:
        print(f"{users} users × {args.requests} requests…", flush=True)
        scenario = await run_scenario(
            args.url, asked, users, args.requests, args.container
        )
        summary = scenario.summary()
        summaries.append(summary)
        print(
            f"  ok {summary['ok']}/{summary['requests']}, done p95 "
            f"{summary['done_ms']['p95']} ms, peak {summary['peak_memory_mib']} MiB",
            flush=True,
        )
    report = render_load(summaries)
    out = _write("load", summaries, report)
    print("\n" + report + f"\nSaved in {out}")
    return 0


async def _coldstart(args: argparse.Namespace) -> int:
    asked = knowledge_questions()
    runs = []
    for i in range(args.runs):
        # Different knowledge questions each run: the first loads both search
        # models, the second shows the warm cost.
        pair = (asked[(2 * i) % len(asked)], asked[(2 * i + 1) % len(asked)])
        print(f"run {i + 1}/{args.runs}: restarting {args.container}…", flush=True)
        result = await cold_start(args.url, args.container, pair)
        runs.append(result.as_dict())
        if result.error:
            print(f"  error: {result.error}", flush=True)
    report = render_coldstart(runs)
    out = _write("coldstart", runs, report)
    print("\n" + report + f"\nSaved in {out}")
    return 0 if all(not r["error"] for r in runs) else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "load":
            return asyncio.run(_load(args))
        return asyncio.run(_coldstart(args))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
