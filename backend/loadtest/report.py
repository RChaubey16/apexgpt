"""Markdown for load and cold-start results (F6.4)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def _ms(value: object) -> str:
    return "–" if value is None else f"{value:,}"


def render_load(summaries: Sequence[dict[str, Any]]) -> str:
    lines = [
        "# Load test",
        "",
        "| Users | OK | Answers/min | First event p50 / p95 | First token p50 / p95 "
        "| Done p50 / p95 / max | Retrieval p50 / p95 | Peak memory | Peak CPU |",
        "|---:|---:|---:|---|---|---|---|---:|---:|",
    ]
    for s in summaries:
        memory = (
            f"{s['peak_memory_mib']} / {s['memory_limit_mib']} MiB"
            if s["peak_memory_mib"] is not None
            else "–"
        )
        cpu = f"{s['peak_cpu_percent']}%" if s["peak_cpu_percent"] is not None else "–"
        fe, ft, done, rt = (
            s["first_event_ms"],
            s["first_token_ms"],
            s["done_ms"],
            s["retrieval_ms"],
        )
        lines.append(
            f"| {s['users']} | {s['ok']}/{s['requests']} | {s['throughput_per_minute']} "
            f"| {_ms(fe['p50'])} / {_ms(fe['p95'])} | {_ms(ft['p50'])} / {_ms(ft['p95'])} "
            f"| {_ms(done['p50'])} / {_ms(done['p95'])} / {_ms(done['max'])} "
            f"| {_ms(rt['p50'])} / {_ms(rt['p95'])} | {memory} | {cpu} |"
        )
    problems = [s for s in summaries if s["ok"] < s["requests"]]
    if problems:
        lines += ["", "## Failed requests", ""]
        for s in problems:
            outcomes = ", ".join(f"{k}: {v}" for k, v in s["outcomes"].items())
            lines.append(f"- {s['users']} users: {outcomes}")
            lines += [f"  - {e}" for e in s["errors"]]
    lines += ["", "Times in ms from sending the request."]
    return "\n".join(lines) + "\n"


def render_coldstart(runs: Sequence[dict[str, Any]]) -> str:
    lines = [
        "# Cold start",
        "",
        "| Run | /health | /health/ready | 1st answer: first token / done "
        "| 1st retrieval | 2nd answer: done | 2nd retrieval | Memory after |",
        "|---:|---:|---:|---|---:|---:|---:|---:|",
    ]
    for i, r in enumerate(runs, 1):
        first, second = r.get("first") or {}, r.get("second") or {}
        lines.append(
            f"| {i} | {_ms(r['health_ms'])} | {_ms(r['ready_ms'])} "
            f"| {_ms(first.get('first_token_ms'))} / {_ms(first.get('done_ms'))} "
            f"| {_ms((first.get('tool_ms') or {}).get('search_f1_knowledge'))} "
            f"| {_ms(second.get('done_ms'))} "
            f"| {_ms((second.get('tool_ms') or {}).get('search_f1_knowledge'))} "
            f"| {_ms(r['memory_after_mib'])} MiB |"
        )
    errors = [(i, r["error"]) for i, r in enumerate(runs, 1) if r["error"]]
    for i, r in enumerate(runs, 1):
        for key in ("first", "second"):
            req = r.get(key) or {}
            if req and req.get("outcome") != "ok":
                errors.append(
                    (i, f"{key} answer: {req.get('outcome')} {req.get('error')}")
                )
    if errors:
        lines += ["", "## Errors", ""] + [f"- run {i}: {e}" for i, e in errors]
    lines += [
        "",
        "/health and /health/ready in ms after `docker restart` started; answer "
        "times in ms from sending each request.",
    ]
    return "\n".join(lines) + "\n"
