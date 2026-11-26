"""Running golden questions through the answer pipeline (F6.2).

A run lives in its own directory (default ``data/eval/runs/<UTC time>``):

- ``meta.json``:     when, git commit, providers, the questions asked;
- ``results.jsonl``: one ``QuestionResult`` per line, appended as each question
                     finishes, so an interrupted run can be resumed;
- ``report.md``:     the summary (``evals.report``).

Live runs spend free-tier LLM quota (an answer is ~4–8k tokens, plus ~1k for the
judge), so select questions with ``--category`` / ``--id`` while iterating.
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from app.answer import Answer, AnswerUnavailableError
from app.answer.followups import HistoryMessage
from evals.golden import DEFAULT_PATH, GoldenQuestion, GoldenSet
from evals.judge import JudgeError
from evals.scoring import (
    JudgeVerdict,
    Observed,
    QuestionResult,
    check_answer,
    check_judgement,
    needs_judge,
)

logger = logging.getLogger(__name__)

REPO_ROOT = DEFAULT_PATH.parents[1]
RUNS_DIR = REPO_ROOT / "data" / "eval" / "runs"
RESULTS_FILE = "results.jsonl"
META_FILE = "meta.json"
REPORT_FILE = "report.md"

Answerer = Callable[[str, Sequence[HistoryMessage]], Answer]
JudgeFn = Callable[[GoldenQuestion, Observed], JudgeVerdict]


class RunError(Exception):
    """A run can't start or continue (bad selection, unreadable results)."""


# --- selecting questions -----------------------------------------------------


def select(
    golden: GoldenSet,
    *,
    categories: Iterable[str] = (),
    ids: Iterable[str] = (),
    limit: int | None = None,
) -> list[GoldenQuestion]:
    """Questions in file order, filtered by category and/or id (both: either)."""
    categories, ids = set(categories), list(ids)
    known_ids = {q.id for q in golden.questions}
    unknown = [i for i in ids if i not in known_ids]
    if unknown:
        raise RunError(f"unknown question ids: {', '.join(unknown)}")
    known_categories = {q.category.value for q in golden.questions}
    unknown = sorted(categories - known_categories)
    if unknown:
        raise RunError(f"unknown categories: {', '.join(unknown)}")
    if limit is not None and limit < 1:
        raise RunError("limit must be at least 1")

    chosen = [
        q
        for q in golden.questions
        if (not categories and not ids) or q.category in categories or q.id in ids
    ]
    return chosen[:limit] if limit is not None else chosen


# --- results files ------------------------------------------------------------


def load_results(run_dir: Path) -> dict[str, QuestionResult]:
    """The latest result per question id (a resumed run appends retries)."""
    path = run_dir / RESULTS_FILE
    if not path.exists():
        return {}
    results: dict[str, QuestionResult] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RunError(f"cannot read {path}: {exc}") from exc
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            result = QuestionResult.model_validate_json(line)
        except ValidationError as exc:
            raise RunError(f"{path}:{number} is not a valid result") from exc
        results[result.id] = result
    return results


def append_result(run_dir: Path, result: QuestionResult) -> None:
    with (run_dir / RESULTS_FILE).open("a", encoding="utf-8") as f:
        f.write(result.model_dump_json() + "\n")
        f.flush()


class RunMeta(BaseModel):
    model_config = ConfigDict(frozen=True)

    started_at: str
    git_commit: str | None
    golden_sha256: str
    provider: str | None  # pinned answer provider, None = fallback chain
    judge_provider: str | None
    judge: bool
    question_ids: tuple[str, ...]


def git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607 (git on PATH)
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def new_run_dir(base: Path = RUNS_DIR, label: str | None = None) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    name = f"{stamp}-{label}" if label else stamp
    run_dir = base / name
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def write_meta(run_dir: Path, meta: RunMeta) -> None:
    (run_dir / META_FILE).write_text(meta.model_dump_json(indent=2) + "\n")


def read_meta(run_dir: Path) -> RunMeta | None:
    path = run_dir / META_FILE
    if not path.exists():
        return None
    try:
        return RunMeta.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise RunError(f"cannot read {path}: {exc}") from exc


# --- answering and scoring ------------------------------------------------------


def evaluate(
    question: GoldenQuestion,
    answerer: Answerer,
    judge: JudgeFn | None,
    *,
    retries: int = 1,
    retry_wait: float = 60.0,
    sleep: Callable[[float], None] = time.sleep,
) -> QuestionResult:
    """Answer one question and score it. Never raises for an expected failure:
    no answer becomes a result with ``error``; a failed judge, ERROR checks."""
    history = [HistoryMessage(m.role, m.content) for m in question.history]
    base = {
        "id": question.id,
        "category": question.category.value,
        "question": question.question,
    }

    answer: Answer | None = None
    error = None
    for attempt in range(retries + 1):
        try:
            answer = answerer(question.question, history)
            break
        except AnswerUnavailableError as exc:
            # Usually every provider is rate limited; their limits reset in
            # about a minute, so wait and try again.
            error = str(exc)
            if attempt < retries:
                logger.warning(
                    "%s: no answer (%s); retrying in %.0f s",
                    question.id,
                    error,
                    retry_wait,
                )
                sleep(retry_wait)
        except ValueError as exc:
            error = f"rejected: {exc}"
            break
    if answer is None:
        return QuestionResult(**base, error=error or "no answer")

    observed = Observed.from_answer(answer)
    checks = check_answer(question, observed)
    verdict = None
    if judge is not None and needs_judge(question):
        try:
            verdict = judge(question, observed)
            checks += check_judgement(question, verdict)
        except JudgeError as exc:
            checks += check_judgement(question, None, str(exc))
    return QuestionResult(
        **base, observed=observed, judge=verdict, checks=tuple(checks)
    )


@dataclass
class RunOptions:
    retries: int = 1
    retry_wait: float = 60.0
    delay: float = 0.0  # seconds between questions (free-tier pacing)


def run(
    questions: Sequence[GoldenQuestion],
    run_dir: Path,
    answerer: Answerer,
    judge: JudgeFn | None,
    options: RunOptions | None = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
    progress: Callable[[str], None] = print,
) -> list[QuestionResult]:
    """Evaluate the questions not already done in ``run_dir`` (a resumed run
    skips questions with a result that isn't an error), appending each result
    as it finishes. Returns every result for these questions."""
    options = options or RunOptions()
    done = {i: r for i, r in load_results(run_dir).items() if r.error is None}
    todo = [q for q in questions if q.id not in done]
    if done:
        progress(f"Resuming: {len(questions) - len(todo)} done, {len(todo)} to go")

    for index, question in enumerate(todo, 1):
        if index > 1 and options.delay:
            sleep(options.delay)
        result = evaluate(
            question,
            answerer,
            judge,
            retries=options.retries,
            retry_wait=options.retry_wait,
            sleep=sleep,
        )
        append_result(run_dir, result)
        done[question.id] = result
        failed = [c.name for c in result.checks if c.status != "pass"]
        detail = result.error or (", ".join(failed) if failed else "")
        progress(
            f"[{index}/{len(todo)}] {result.status.value.upper():5} {question.id}"
            + (f"  ({detail})" if detail else "")
        )
    return [done[q.id] for q in questions if q.id in done]


# --- retrieval only (no LLM) -----------------------------------------------------


class RetrievalResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    category: str
    query: str
    expected: tuple[str, ...]
    retrieved: tuple[str, ...]  # article titles, best first (repeats kept)

    @property
    def rank(self) -> int | None:
        """1-based position of the first expected article, None if absent."""
        for position, title in enumerate(self.retrieved, 1):
            if title in self.expected:
                return position
        return None


def retrieval_questions(questions: Iterable[GoldenQuestion]) -> list[GoldenQuestion]:
    """Questions with expected sources that can be searched as asked
    (follow-ups need the condenser, so they're left out)."""
    return [q for q in questions if q.expect.sources and not q.history]


def run_retrieval(
    questions: Iterable[GoldenQuestion], retrieve: Callable[[str], list[str]]
) -> list[RetrievalResult]:
    """The question itself as the search query: a proxy for the terms the LLM
    sends to the knowledge tool."""
    return [
        RetrievalResult(
            id=q.id,
            category=q.category.value,
            query=q.question,
            expected=q.expect.sources,
            retrieved=tuple(retrieve(q.question)),
        )
        for q in retrieval_questions(questions)
    ]
