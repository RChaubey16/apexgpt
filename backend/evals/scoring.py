"""Scoring one answer against its golden question (F6.2).

Checks, each applied only when the question expects it:

- ``answer``:     every expected value appears in the answer (exact match after
                  normalising, see ``evals.golden.contains_value``);
- ``tools``:      every expected tool was called successfully;
- ``sources``:    at least one expected article is cited;
- ``standalone``: a follow-up was rewritten to contain the expected values;
- ``facts``:      the LLM judge found every reference fact in the answer;
- ``behavior``:   the judge found the expected behavior (answer, decline,
                  correct the premise).

A question passes when every applicable check passes.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.answer import Answer
from evals.golden import Behavior, GoldenQuestion, contains_value


class Status(StrEnum):
    PASS = "pass"  # noqa: S105 (a status, not a password)
    FAIL = "fail"
    ERROR = "error"  # couldn't be checked (e.g. the judge failed)


class CheckResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    status: Status
    detail: str = ""


class ToolUse(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    ok: bool


class Observed(BaseModel):
    """What the pipeline did for one question (kept in the results file)."""

    model_config = ConfigDict(frozen=True)

    standalone: str  # the question answered (the rewrite, for a follow-up)
    text: str
    tools: tuple[ToolUse, ...] = ()
    cited_titles: tuple[str, ...] = ()
    provider: str = ""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    llm_calls: int = 0

    @classmethod
    def from_answer(cls, answer: Answer) -> Observed:
        return cls(
            standalone=answer.question,
            text=answer.text,
            tools=tuple(ToolUse(name=c.name, ok=c.ok) for c in answer.tool_calls),
            cited_titles=tuple(dict.fromkeys(s.title for s in answer.sources)),
            provider=answer.provider,
            model=answer.model,
            prompt_tokens=answer.prompt_tokens,
            completion_tokens=answer.completion_tokens,
            latency_ms=answer.latency_ms,
            llm_calls=answer.llm_calls,
        )


FactVerdict = str  # "supported" | "missing" | "contradicted"


class JudgeVerdict(BaseModel):
    model_config = ConfigDict(frozen=True)

    behavior_ok: bool
    facts: tuple[FactVerdict, ...]
    reason: str = ""
    provider: str = ""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0


def needs_judge(question: GoldenQuestion) -> bool:
    expect = question.expect
    return bool(expect.facts) or expect.behavior is not Behavior.ANSWER


def _missing(text: str, values: tuple[str, ...]) -> list[str]:
    return [v for v in values if not contains_value(text, v)]


def check_answer(question: GoldenQuestion, observed: Observed) -> list[CheckResult]:
    """The checks that need no LLM."""
    expect = question.expect
    checks: list[CheckResult] = []

    if expect.answer:
        missing = _missing(observed.text, expect.answer)
        checks.append(
            CheckResult(name="answer", status=Status.PASS)
            if not missing
            else CheckResult(
                name="answer", status=Status.FAIL, detail=f"missing {missing}"
            )
        )

    if expect.tools:
        used = {t.name for t in observed.tools if t.ok}
        failed = sorted({t.name for t in observed.tools if not t.ok} - used)
        missing_tools = [t for t in expect.tools if t not in used]
        detail = f"not used: {missing_tools}" if missing_tools else ""
        if failed:
            detail = f"{detail}; failed calls: {failed}".lstrip("; ")
        checks.append(
            CheckResult(
                name="tools",
                status=Status.FAIL if missing_tools else Status.PASS,
                detail=detail,
            )
        )

    if expect.sources:
        cited = set(observed.cited_titles)
        hit = [s for s in expect.sources if s in cited]
        checks.append(
            CheckResult(name="sources", status=Status.PASS, detail=f"cited {hit}")
            if hit
            else CheckResult(
                name="sources",
                status=Status.FAIL,
                detail=(
                    f"cited {list(observed.cited_titles) or 'nothing'}; "
                    f"expected one of {list(expect.sources)}"
                ),
            )
        )

    if expect.standalone:
        missing = _missing(observed.standalone, expect.standalone)
        checks.append(
            CheckResult(name="standalone", status=Status.PASS)
            if not missing
            else CheckResult(
                name="standalone",
                status=Status.FAIL,
                detail=f"rewrite {observed.standalone!r} is missing {missing}",
            )
        )
    return checks


def check_judgement(
    question: GoldenQuestion, verdict: JudgeVerdict | None, error: str | None = None
) -> list[CheckResult]:
    """The facts and behavior checks from the judge's verdict."""
    names = ["behavior"] + (["facts"] if question.expect.facts else [])
    if verdict is None:
        detail = f"judge failed: {error}" if error else "judge failed"
        return [CheckResult(name=n, status=Status.ERROR, detail=detail) for n in names]

    checks = [
        CheckResult(
            name="behavior",
            status=Status.PASS if verdict.behavior_ok else Status.FAIL,
            detail="" if verdict.behavior_ok else verdict.reason,
        )
    ]
    if question.expect.facts:
        bad = [
            f"{fact} ({v})"
            for fact, v in zip(question.expect.facts, verdict.facts, strict=True)
            if v != "supported"
        ]
        checks.append(
            CheckResult(name="facts", status=Status.PASS)
            if not bad
            else CheckResult(name="facts", status=Status.FAIL, detail="; ".join(bad))
        )
    return checks


class QuestionResult(BaseModel):
    """One line of a run's results file."""

    model_config = ConfigDict(frozen=True)

    id: str
    category: str
    question: str
    observed: Observed | None = None
    judge: JudgeVerdict | None = None
    checks: tuple[CheckResult, ...] = ()
    error: str | None = None  # no answer at all

    @property
    def status(self) -> Status:
        if self.error is not None:
            return Status.ERROR
        statuses = {c.status for c in self.checks}
        if Status.FAIL in statuses:
            return Status.FAIL
        if Status.ERROR in statuses:
            return Status.ERROR
        return Status.PASS
