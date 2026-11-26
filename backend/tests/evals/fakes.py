"""Shared fakes for the eval tests: answers, golden questions, an LLM."""

from __future__ import annotations

from collections.abc import Sequence

import yaml

from app.answer import Answer, ToolCallRecord
from app.llm import LLMResponse, Usage
from app.tools.base import Source
from evals.golden import GoldenQuestion, GoldenSet, parse_golden_set


def question(**fields: object) -> GoldenQuestion:
    base: dict[str, object] = {
        "id": "q-1",
        "category": "races",
        "question": "Who won the 1990 Japanese Grand Prix?",
        "expect": {"answer": ["Nelson Piquet"]},
    }
    base.update(fields)
    return golden_set(base).questions[0]


def golden_set(*questions: dict[str, object]) -> GoldenSet:
    return parse_golden_set(
        yaml.safe_dump({"version": 1, "questions": list(questions)})
    )


def answer(
    text: str = "Nelson Piquet won it.",
    *,
    question_text: str = "Who won the 1990 Japanese Grand Prix?",
    tools: Sequence[tuple[str, bool]] = (),
    titles: Sequence[str] = (),
    provider: str = "groq",
    latency_ms: int = 1000,
) -> Answer:
    return Answer(
        question=question_text,
        text=text,
        sources=tuple(
            Source(id=f"S{i}", title=t, url=f"https://en.wikipedia.org/wiki/{i}")
            for i, t in enumerate(titles, 1)
        ),
        tool_calls=tuple(ToolCallRecord(n, {}, ok) for n, ok in tools),
        resolution=None,
        provider=provider,
        model=f"{provider}-model",
        prompt_tokens=3000,
        completion_tokens=500,
        latency_ms=latency_ms,
        llm_calls=2,
    )


class ReplyingLLM:
    """complete() returns the scripted replies in order (or raises them)."""

    def __init__(self, *replies: str | Exception) -> None:
        self.replies = list(replies)
        self.messages: list[list[dict]] = []
        self.kwargs: list[dict] = []

    def complete(self, messages, **kwargs) -> LLMResponse:  # noqa: ANN001
        self.messages.append(list(messages))
        self.kwargs.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return LLMResponse(
            content=reply,
            tool_calls=(),
            finish_reason="stop",
            provider="gemini",
            model="judge-model",
            usage=Usage(prompt_tokens=800, completion_tokens=120),
            latency_ms=500,
        )
