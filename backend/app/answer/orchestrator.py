"""Answer orchestrator: question → names → tools → grounded, cited answer (F3.7).

    orchestrator = build_orchestrator(settings)
    answer = orchestrator.answer("Who has the most wins at Monza?")
    answer.text, answer.sources, answer.tool_calls

1. Entity resolution (F3.4) finds the names in the question; the best guesses
   and alternatives go into the user message as hints (refs the SQL views use).
   If it fails, the question goes on without hints.
2. The LLM is offered the tools (query_stats, search_f1_knowledge) for up to
   MAX_ROUNDS rounds and MAX_TOOL_CALLS calls in total. Every call's outcome
   (rows, passages or an error message) goes back to it; knowledge sources are
   numbered S1, S2, … across calls.
3. When the rounds or calls run out, one last request without tools makes it
   answer from what it has.
4. Citation markers that don't match a source are removed; the answer lists
   the sources it cites.

Expected failures inside a tool become messages to the model (app/tools/base);
only an LLM that can't answer at all raises AnswerUnavailableError.
"""

import json
import logging
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.answer.prompts import FINAL_ROUND_NOTE, SYSTEM_PROMPT, user_message
from app.llm.client import LLMClient, LLMResponse
from app.llm.errors import LLMError
from app.retrieval.entities import EntityResolver, Resolution
from app.retrieval.errors import SearchError
from app.retrieval.search import normalise_query
from app.tools.base import Source, Tool, ToolOutcome

logger = logging.getLogger(__name__)

MAX_ROUNDS = 3
MAX_TOOL_CALLS = 4
# Output reservations. Groq's free tier counts prompt + max_tokens against a
# per-minute token budget (8,000 for gpt-oss-120b), so they are kept small:
# a narrative answer is ~2 requests of ~2-3.5k prompt tokens each.
MAX_TOOL_ROUND_TOKENS = 900
MAX_ANSWER_TOKENS = 1000
_CITATION = re.compile(r"\[(S\d+)\]")
# Other ways models write a citation, normalised to "[S3]" first: full-width
# brackets and line suffixes ("【S3】", "【S3†L10-L12】", "[S3†L2]") as gpt-oss does.
_VARIANT = re.compile(r"[\[【]\s*(S\d+)\s*(?:†[^\]】]*)?[\]】]")
# "[S1, S2]" or "[S1; S3]" -> "[S1][S2]", so each id is checked on its own.
_GROUPED = re.compile(r"\[(S\d+(?:\s*[,;]\s*S\d+)+)\]")
_EMPTY_BRACKETS = re.compile(r"\[\s*(?:,\s*)*\]")


class AnswerUnavailableError(LLMError):
    """No answer could be produced (every LLM provider failed)."""


@dataclass(frozen=True)
class ToolCallRecord:
    name: str
    arguments: dict[str, Any]
    ok: bool
    error: str | None = None


@dataclass(frozen=True)
class Answer:
    question: str
    text: str
    # Sources the answer cites, in order of first citation.
    sources: tuple[Source, ...]
    tool_calls: tuple[ToolCallRecord, ...]
    resolution: Resolution | None
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    llm_calls: int = field(default=0)


def clean_citations(
    text: str, known: dict[str, Source]
) -> tuple[str, tuple[Source, ...]]:
    """Drop [S#] markers that match no source; return the cited sources in order."""
    cited: list[Source] = []

    def keep(match: re.Match[str]) -> str:
        source_id = match.group(1)
        if source_id not in known:
            return ""
        if known[source_id] not in cited:
            cited.append(known[source_id])
        return match.group(0)

    text = _VARIANT.sub(r"[\1]", text.replace("【", "[").replace("】", "]"))
    text = _GROUPED.sub(
        lambda m: "".join(f"[{i.strip()}]" for i in re.split(r"[,;]", m.group(1))), text
    )
    cleaned = _CITATION.sub(keep, text)
    cleaned = _EMPTY_BRACKETS.sub("", cleaned)
    cleaned = re.sub(r"[ \t]+([.,;:])", r"\1", cleaned)  # "fact [S9]." -> "fact."
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    return cleaned, tuple(cited)


def _assistant_tool_message(response: LLMResponse) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": response.content or None,
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments),
                },
            }
            for call in response.tool_calls
        ],
    }


class Orchestrator:
    def __init__(
        self,
        llm: LLMClient,
        tools: Sequence[Tool],
        resolver: EntityResolver | None = None,
        *,
        max_rounds: int = MAX_ROUNDS,
        max_tool_calls: int = MAX_TOOL_CALLS,
    ) -> None:
        self._llm = llm
        self._tools = {tool.name: tool for tool in tools}
        self._resolver = resolver
        self._max_rounds = max_rounds
        self._max_tool_calls = max_tool_calls
        self._definitions: list[dict[str, Any]] | None = None

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools)

    def _tool_definitions(self) -> list[dict[str, Any]]:
        """Definitions of the tools that are available; one that can't describe
        itself (e.g. the stats database is down) is left out, not fatal."""
        if self._definitions is None:
            definitions = []
            for name, tool in self._tools.items():
                try:
                    definitions.append(tool.definition())
                except (
                    Exception
                ) as exc:  # noqa: BLE001 - a broken tool must not stop answers
                    logger.warning("Tool %s unavailable: %s", name, type(exc).__name__)
            self._definitions = definitions
        return self._definitions

    def _resolve(self, question: str) -> Resolution | None:
        if self._resolver is None:
            return None
        try:
            return self._resolver.resolve(question)
        except SearchError as exc:
            logger.warning("Entity resolution skipped: %s", type(exc).__name__)
            return None

    def _run_tool(
        self, name: str, arguments: dict[str, Any], next_source: int
    ) -> ToolOutcome:
        tool = self._tools.get(name)
        if tool is None:
            return ToolOutcome.error(
                name, f"unknown tool {name!r}; use {', '.join(self._tools)}"
            )
        return tool.call(arguments, first_source_number=next_source)

    def answer(self, question: str) -> Answer:
        """A grounded answer to one question. Raises ValueError for a bad
        question and AnswerUnavailableError when no LLM provider can answer."""
        question = normalise_query(question)
        started = time.perf_counter()
        resolution = self._resolve(question)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message(question, resolution)},
        ]
        definitions = self._tool_definitions()
        sources: dict[str, Source] = {}
        records: list[ToolCallRecord] = []
        prompt_tokens = completion_tokens = llm_calls = 0
        response: LLMResponse | None = None

        try:
            for round_number in range(1, self._max_rounds + 2):
                final = (
                    not definitions
                    or round_number > self._max_rounds
                    or len(records) >= self._max_tool_calls
                )
                if final and records:
                    messages.append({"role": "user", "content": FINAL_ROUND_NOTE})
                response = self._llm.complete(
                    messages,
                    tools=None if final else definitions,
                    max_tokens=MAX_ANSWER_TOKENS if final else MAX_TOOL_ROUND_TOKENS,
                )
                if response.finish_reason == "length":
                    logger.warning("LLM output hit max_tokens (round %d)", round_number)
                llm_calls += 1
                if response.usage:
                    prompt_tokens += response.usage.prompt_tokens
                    completion_tokens += response.usage.completion_tokens
                if final or not response.tool_calls:
                    break

                messages.append(_assistant_tool_message(response))
                for call in response.tool_calls:
                    if len(records) >= self._max_tool_calls:
                        outcome = ToolOutcome.error(
                            call.name,
                            "tool call limit reached; answer with what you have",
                        )
                    else:
                        outcome = self._run_tool(
                            call.name, call.arguments, len(sources) + 1
                        )
                        for source in outcome.sources:
                            sources[source.id] = source
                        records.append(
                            ToolCallRecord(
                                call.name,
                                call.arguments,
                                outcome.ok,
                                None if outcome.ok else outcome.payload.get("error"),
                            )
                        )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": json.dumps(outcome.payload, ensure_ascii=False),
                        }
                    )
        except LLMError as exc:
            logger.warning("No answer: %s", type(exc).__name__)
            raise AnswerUnavailableError(str(exc)) from None

        if response is None:  # unreachable: the loop always runs once
            raise AnswerUnavailableError("The language model returned no answer")
        text, cited = clean_citations(response.content or "", sources)
        if not text:
            raise AnswerUnavailableError("The language model returned an empty answer")
        latency = round((time.perf_counter() - started) * 1000)
        logger.info(
            "Answered: tools=%s llm_calls=%d sources=%d/%d tokens=%d+%d latency_ms=%d",
            [r.name for r in records],
            llm_calls,
            len(cited),
            len(sources),
            prompt_tokens,
            completion_tokens,
            latency,
        )
        return Answer(
            question=question,
            text=text,
            sources=cited,
            tool_calls=tuple(records),
            resolution=resolution,
            provider=response.provider,
            model=response.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency,
            llm_calls=llm_calls,
        )
