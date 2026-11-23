"""Answer orchestrator: question → names → tools → grounded, cited answer
(F3.7), streamed as events (F4.1).

    orchestrator = build_orchestrator(settings)
    for event in orchestrator.stream("Explain Abu Dhabi 2021"):
        ...  # ToolEvent, TableEvent, TokenEvent, CitationEvent, then DoneEvent
    answer = orchestrator.answer("Who has the most wins at Monza?")  # the same, collected

1. Entity resolution (F3.4) finds the names in the question; the best guesses
   and alternatives go into the user message as hints (refs the SQL views use).
   If it fails, the question goes on without hints.
2. Every round is streamed with the tools offered (LLMClient.stream_turn): tool
   calls are collected and run, text streams to the caller as it arrives. Up to
   MAX_ROUNDS rounds and MAX_TOOL_CALLS calls; every outcome (rows, passages
   or an error message) goes back to the model, and knowledge sources are
   numbered S1, S2, … across calls.
3. When the rounds or calls run out, one last request without tools makes it
   answer from what it has.
4. Citations are checked while streaming (CitationFilter): a possible marker
   is held back until it is complete, then normalised ("【S3】" → "[S3]") or
   dropped when it names no source. Each newly cited source is an event.

Expected failures inside a tool become messages to the model (app/tools/base);
only an LLM that can't answer at all raises AnswerUnavailableError (possibly
after some tokens were sent, when a stream is interrupted).
"""

import json
import logging
import re
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from app.answer.prompts import FINAL_ROUND_NOTE, SYSTEM_PROMPT, user_message
from app.llm.client import PROVIDER_KEY, LLMClient, Turn
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
# A '[' with no closing bracket this far on is not a citation.
MAX_MARKER_CHARS = 40
_OPENERS = "[【"
_CLOSERS = "]】"
_SOURCE_ID = re.compile(r"^S\d+$")
_AFTER_DROPPED = set(" \t\n.,;:!?)")


class AnswerUnavailableError(LLMError):
    """No answer could be produced (every LLM provider failed, or the stream
    was interrupted)."""


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


# --- events ---


@dataclass(frozen=True)
class ToolEvent:
    name: str
    status: Literal["started", "finished"]
    ok: bool | None = None  # set when finished


@dataclass(frozen=True)
class TableEvent:
    """Rows a stats query returned (for the UI to show exactly)."""

    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    note: str | None = None


@dataclass(frozen=True)
class TokenEvent:
    text: str


@dataclass(frozen=True)
class CitationEvent:
    source: Source


@dataclass(frozen=True)
class DoneEvent:
    answer: Answer


AnswerEvent = ToolEvent | TableEvent | TokenEvent | CitationEvent | DoneEvent


# --- citations ---


class CitationFilter:
    """Checks citations in streamed text.

    Text is released as soon as it can't be part of a citation; from a '[' or
    '【' it is held until the closing bracket (or MAX_MARKER_CHARS), then:
    - "[S3]", "【S3】", "[S3†L2]", "[S1, S2]" → "[S3]", "[S1][S2]" for known ids;
    - a marker naming only unknown ids is dropped with the space before it;
    - anything else in brackets ("[link](url)", "[note]") is left alone.
    Whitespace before a held marker is held with it, so "fact [S9]." → "fact.".
    `known` is shared: sources added to it later count as soon as they exist.
    """

    def __init__(self, known: dict[str, Source]) -> None:
        self._known = known
        self._pending = ""
        self._cited: list[Source] = []
        self._started = False

    @property
    def cited(self) -> tuple[Source, ...]:
        return tuple(self._cited)

    def feed(self, text: str) -> tuple[str, list[Source]]:
        self._pending += text
        return self._drain(final=False)

    def flush(self) -> tuple[str, list[Source]]:
        return self._drain(final=True)

    def _marker(self, marker: str, new: list[Source]) -> str | None:
        """Normalised replacement for a bracketed marker, or None if it isn't
        a citation."""
        inner = marker[1:-1].split("†", 1)[0]
        ids = [part.strip() for part in re.split(r"[,;]", inner)]
        if not ids or not all(_SOURCE_ID.match(i) for i in ids):
            return None
        kept = []
        for source_id in ids:
            source = self._known.get(source_id)
            if source is None:
                continue
            kept.append(f"[{source_id}]")
            if source not in self._cited:
                self._cited.append(source)
                new.append(source)
        return "".join(kept)

    def _drain(self, *, final: bool) -> tuple[str, list[Source]]:
        out: list[str] = []
        new: list[Source] = []
        while True:
            pending = self._pending
            opener = min(
                (i for i in (pending.find(c) for c in _OPENERS) if i >= 0), default=-1
            )
            if opener < 0:
                keep = len(pending) if final else len(pending.rstrip(" \t"))
                out.append(pending[:keep])
                self._pending = pending[keep:]
                break
            # Release the text before the marker, minus the whitespace right before it.
            head = pending[:opener]
            cut = len(head.rstrip(" \t"))
            out.append(head[:cut])
            pending = self._pending = pending[cut:]
            start = opener - cut
            close = min(
                (i for i in (pending.find(c, start) for c in _CLOSERS) if i >= 0),
                default=-1,
            )
            if close < 0:
                if final or len(pending) - start > MAX_MARKER_CHARS:
                    out.append(pending[: start + 1])  # just a bracket
                    self._pending = pending[start + 1 :]
                    continue
                break  # wait for the rest of the marker
            space, marker, rest = (
                pending[:start],
                pending[start : close + 1],
                pending[close + 1 :],
            )
            replacement = self._marker(marker, new)
            if replacement is None:
                out.append(space + marker)
            elif replacement:
                out.append(space + replacement)
            elif not rest and not final:
                break  # dropped marker: wait to see what follows it
            elif rest and rest[0] not in _AFTER_DROPPED:
                out.append(space)
            self._pending = rest
        text = "".join(out)
        if not self._started:
            text = text.lstrip()
            self._started = bool(text)
        return text, new


def clean_citations(
    text: str, known: dict[str, Source]
) -> tuple[str, tuple[Source, ...]]:
    """Check the citations in a complete text (see CitationFilter)."""
    citations = CitationFilter(known)
    first, _ = citations.feed(text)
    rest, _ = citations.flush()
    return (first + rest).strip(), citations.cited


def _assistant_tool_message(turn: Turn) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": turn.content or None,
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments),
                },
                **call.extra,  # e.g. Gemini's thought_signature
            }
            for call in turn.tool_calls
        ],
        # Another provider gets this history as plain text (LLMClient).
        PROVIDER_KEY: turn.provider,
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

    @property
    def llm(self) -> LLMClient:
        return self._llm

    def close(self) -> None:
        """Release what the tools hold (e.g. the stats connection pool)."""
        for tool in self._tools.values():
            dispose = getattr(tool, "dispose", None)
            if callable(dispose):
                dispose()

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
        """The whole answer at once (the CLI and tests): stream() collected."""
        for event in self.stream(question):
            if isinstance(event, DoneEvent):
                return event.answer
        raise AnswerUnavailableError(
            "The language model returned no answer"
        )  # unreachable

    def stream(self, question: str) -> Iterator[AnswerEvent]:
        """Events for one question, ending with DoneEvent. Raises ValueError for
        a bad question (before any event) and AnswerUnavailableError when no
        provider can answer or the stream breaks off."""
        question = normalise_query(question)
        return self._stream(question)

    def _stream(self, question: str) -> Iterator[AnswerEvent]:
        started = time.perf_counter()
        resolution = self._resolve(question)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message(question, resolution)},
        ]
        definitions = self._tool_definitions()
        sources: dict[str, Source] = {}
        citations = CitationFilter(sources)
        text_parts: list[str] = []
        records: list[ToolCallRecord] = []
        prompt_tokens = completion_tokens = llm_calls = 0
        provider = model = ""

        def emit(text: str, new: list[Source]) -> Iterator[AnswerEvent]:
            if text:
                text_parts.append(text)
                yield TokenEvent(text)
            for source in new:
                yield CitationEvent(source)

        try:
            for round_number in range(1, self._max_rounds + 2):
                final = (
                    not definitions
                    or round_number > self._max_rounds
                    or len(records) >= self._max_tool_calls
                )
                if final and records:
                    messages.append({"role": "user", "content": FINAL_ROUND_NOTE})
                turn = self._llm.stream_turn(
                    messages,
                    tools=None if final else definitions,
                    max_tokens=MAX_ANSWER_TOKENS if final else MAX_TOOL_ROUND_TOKENS,
                )
                llm_calls += 1
                provider, model = turn.provider, turn.model
                for piece in turn:  # nothing for a tool-call round
                    yield from emit(*citations.feed(piece))
                if turn.usage:
                    prompt_tokens += turn.usage.prompt_tokens
                    completion_tokens += turn.usage.completion_tokens
                if turn.finish_reason == "length":
                    logger.warning("LLM output hit max_tokens (round %d)", round_number)
                if final or not turn.tool_calls:
                    break

                messages.append(_assistant_tool_message(turn))
                for call in turn.tool_calls:
                    if len(records) >= self._max_tool_calls:
                        outcome = ToolOutcome.error(
                            call.name,
                            "tool call limit reached; answer with what you have",
                        )
                    else:
                        yield ToolEvent(call.name, "started")
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
                        yield ToolEvent(call.name, "finished", outcome.ok)
                        if outcome.ok and "columns" in outcome.payload:
                            yield TableEvent(
                                tuple(outcome.payload["columns"]),
                                tuple(
                                    tuple(r) for r in outcome.payload.get("rows", [])
                                ),
                                outcome.payload.get("note"),
                            )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": json.dumps(outcome.payload, ensure_ascii=False),
                        }
                    )
            yield from emit(*citations.flush())
        except LLMError as exc:
            logger.warning("No answer: %s", type(exc).__name__)
            raise AnswerUnavailableError(str(exc)) from None

        text = "".join(text_parts).strip()
        if not text:
            raise AnswerUnavailableError("The language model returned an empty answer")
        latency = round((time.perf_counter() - started) * 1000)
        logger.info(
            "Answered: tools=%s llm_calls=%d sources=%d/%d tokens=%d+%d latency_ms=%d",
            [r.name for r in records],
            llm_calls,
            len(citations.cited),
            len(sources),
            prompt_tokens,
            completion_tokens,
            latency,
        )
        yield DoneEvent(
            Answer(
                question=question,
                text=text,
                sources=citations.cited,
                tool_calls=tuple(records),
                resolution=resolution,
                provider=provider,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency,
                llm_calls=llm_calls,
            )
        )
