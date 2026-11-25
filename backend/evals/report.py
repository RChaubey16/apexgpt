"""Markdown reports for eval runs (F6.2)."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence

from evals.runner import RetrievalResult, RunMeta
from evals.scoring import QuestionResult, Status

EXCERPT_CHARS = 300


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.0f}%" if whole else "–"


def percentile(values: Sequence[int], p: float) -> int | None:
    """Nearest-rank percentile (p in 0–100); None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(p / 100 * len(ordered)))
    return ordered[rank - 1]


def _group_table(
    title: str,
    results: Iterable[QuestionResult],
    key: Callable[[QuestionResult], str],
) -> list[str]:
    groups: dict[str, list[QuestionResult]] = defaultdict(list)
    for r in results:
        groups[key(r)].append(r)
    lines = [f"| {title} | Questions | Passed | Failed | Errors | Pass rate |"]
    lines.append("|---|---:|---:|---:|---:|---:|")
    for name in sorted(groups):
        rs = groups[name]
        counts = {s: sum(r.status is s for r in rs) for s in Status}
        lines.append(
            f"| {name} | {len(rs)} | {counts[Status.PASS]} | {counts[Status.FAIL]}"
            f" | {counts[Status.ERROR]} | {_pct(counts[Status.PASS], len(rs))} |"
        )
    return lines


def _check_table(results: Sequence[QuestionResult]) -> list[str]:
    by_check: dict[str, list[Status]] = defaultdict(list)
    for r in results:
        for c in r.checks:
            by_check[c.name].append(c.status)
    order = ["answer", "tools", "sources", "standalone", "behavior", "facts"]
    lines = ["| Check | Applied | Passed | Failed | Errors | Pass rate |"]
    lines.append("|---|---:|---:|---:|---:|---:|")
    for name in sorted(
        by_check, key=lambda n: (order.index(n) if n in order else 99, n)
    ):
        statuses = by_check[name]
        passed = statuses.count(Status.PASS)
        lines.append(
            f"| {name} | {len(statuses)} | {passed} | {statuses.count(Status.FAIL)}"
            f" | {statuses.count(Status.ERROR)} | {_pct(passed, len(statuses))} |"
        )
    return lines


def _cell(text: str) -> str:
    return " ".join(text.replace("|", "\\|").split())


def render_run(results: Sequence[QuestionResult], meta: RunMeta | None = None) -> str:
    total = len(results)
    passed = sum(r.status is Status.PASS for r in results)
    errors = sum(r.status is Status.ERROR for r in results)
    lines = ["# ApexGPT eval run", ""]
    if meta is not None:
        pinned = meta.provider or "fallback chain"
        judge = "off" if not meta.judge else (meta.judge_provider or "fallback chain")
        lines += [
            f"- Started: {meta.started_at}",
            f"- Commit: `{meta.git_commit or 'unknown'}`",
            f"- Golden set: `{meta.golden_sha256[:12]}`",
            f"- Answer provider: {pinned} · judge: {judge}",
            "",
        ]
    lines += [
        f"**{passed}/{total} passed ({_pct(passed, total)})**"
        + (f", {errors} with errors" if errors else ""),
        "",
    ]
    if not results:
        return "\n".join(lines)

    answered = [r.observed for r in results if r.observed is not None]
    latencies = [o.latency_ms for o in answered]
    tokens = sum(o.prompt_tokens + o.completion_tokens for o in answered)
    judge_tokens = sum(
        r.judge.prompt_tokens + r.judge.completion_tokens for r in results if r.judge
    )
    lines += ["## Cost and speed", ""]
    if answered:
        lines += [
            f"- Answers: {len(answered)}, latency p50 {percentile(latencies, 50)} ms,"
            f" p95 {percentile(latencies, 95)} ms",
            f"- Tokens: {tokens:,} for answers ({tokens // len(answered):,} each),"
            f" {judge_tokens:,} for the judge",
            f"- LLM calls per answer: {sum(o.llm_calls for o in answered) / len(answered):.1f}",
        ]
    lines += [""]

    lines += ["## By category", ""] + _group_table(
        "Category", results, lambda r: r.category
    )
    lines += ["", "## By check", ""] + _check_table(results)
    lines += ["", "## By answer provider", ""] + _group_table(
        "Provider",
        results,
        lambda r: (
            f"{r.observed.provider} · {r.observed.model}" if r.observed else "(none)"
        ),
    )

    problems = [r for r in results if r.status is not Status.PASS]
    lines += ["", f"## Failures and errors ({len(problems)})", ""]
    for r in problems:
        lines.append(f"### `{r.id}` ({r.category}): {r.status.value}")
        lines.append("")
        lines.append(f"- Question: {_cell(r.question)}")
        if r.error:
            lines.append(f"- Error: {_cell(r.error)}")
        if r.observed:
            if r.observed.standalone != r.question:
                lines.append(f"- Understood as: {_cell(r.observed.standalone)}")
            tools = ", ".join(
                t.name + ("" if t.ok else " (failed)") for t in r.observed.tools
            )
            lines.append(f"- Tools: {tools or 'none'}")
            lines.append(f"- Provider: {r.observed.provider} · {r.observed.model}")
        for c in r.checks:
            if c.status is not Status.PASS:
                lines.append(f"- **{c.name}** {c.status.value}: {_cell(c.detail)}")
        if r.observed:
            text = _cell(r.observed.text)
            if len(text) > EXCERPT_CHARS:
                text = text[:EXCERPT_CHARS].rsplit(" ", 1)[0] + " …"
            lines.append(f"- Answer: {text}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_retrieval(results: Sequence[RetrievalResult], k: int, rerank: bool) -> str:
    total = len(results)
    hits = [r for r in results if r.rank is not None]
    mrr = sum(1 / r.rank for r in hits) / total if total else 0.0
    lines = [
        f"# Retrieval eval (top {k}, {'reranked' if rerank else 'hybrid only'})",
        "",
        f"**{len(hits)}/{total} found an expected article ({_pct(len(hits), total)}),"
        f" MRR {mrr:.2f}**",
        "",
        "| Question | Category | Rank | Retrieved |",
        "|---|---|---:|---|",
    ]
    for r in results:
        retrieved = ", ".join(dict.fromkeys(r.retrieved))
        lines.append(
            f"| `{r.id}` | {r.category} | {r.rank or '–'} | {_cell(retrieved)} |"
        )
    misses = [r for r in results if r.rank is None]
    if misses:
        lines += ["", "## Misses", ""]
        for r in misses:
            lines.append(f"- `{r.id}`: expected {list(r.expected)}")
    return "\n".join(lines) + "\n"
