"""The answer orchestrator with a scripted LLM and fake tools (no network, no DB)."""

import json
from typing import Any

import pytest

from app.answer import __main__ as cli
from app.answer.orchestrator import (
    MAX_ANSWER_TOKENS,
    MAX_TOOL_ROUND_TOKENS,
    Answer,
    AnswerUnavailableError,
    Orchestrator,
    clean_citations,
)
from app.answer.prompts import (
    FINAL_ROUND_NOTE,
    SYSTEM_PROMPT,
    entity_hints,
    user_message,
)
from app.llm.client import LLMResponse, ToolCall, Usage
from app.llm.errors import LLMUnavailableError
from app.retrieval.entities import Candidate, Entity, Mention, Resolution
from app.retrieval.errors import SearchError
from app.tools.base import Source, ToolOutcome
from tests.conftest import make_settings


def reply(
    content: str | None = None, *calls: ToolCall, finish: str = "stop"
) -> LLMResponse:
    return LLMResponse(
        content=content,
        tool_calls=tuple(calls),
        finish_reason="tool_calls" if calls else finish,
        provider="groq",
        model="openai/gpt-oss-120b",
        usage=Usage(100, 20),
        latency_ms=5,
    )


def call(name: str, i: int = 1, **arguments: Any) -> ToolCall:
    return ToolCall(f"call_{i}", name, arguments)


class FakeTurn:
    """What LLMClient.stream_turn returns: tool calls, or text in pieces."""

    def __init__(
        self, response: LLMResponse, pieces: list[str] | Exception | None
    ) -> None:
        self.provider, self.model = response.provider, response.model
        self.tool_calls = response.tool_calls
        self.content = response.content or ""
        self.finish_reason = response.finish_reason
        self.usage = response.usage
        self._pieces = pieces

    def __iter__(self):
        if isinstance(self._pieces, Exception):
            yield "Partial "
            raise self._pieces
        yield from self._pieces or []


def pieces_of(text: str | None) -> list[str]:
    """Split a reply into 3-character pieces, like a real stream."""
    return [text[i : i + 3] for i in range(0, len(text), 3)] if text else []


class ScriptedLLM:
    def __init__(self, *responses: LLMResponse | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[dict] = []

    def stream_turn(
        self, messages, *, tools=None, tool_choice=None, max_tokens=1024, **kw
    ):
        self.requests.append(
            {
                "messages": [dict(m) for m in messages],
                "tools": tools,
                "max_tokens": max_tokens,
            }
        )
        outcome = self.responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, tuple):  # (response, error after the first piece)
            return FakeTurn(outcome[0], outcome[1])
        pieces = [] if outcome.tool_calls else pieces_of(outcome.content)
        return FakeTurn(outcome, pieces)


class FakeKnowledge:
    name = "search_f1_knowledge"

    def __init__(self) -> None:
        self.calls: list[tuple[dict, int]] = []

    def definition(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "parameters": {}}}

    def call(self, arguments, *, first_source_number=1, **context) -> ToolOutcome:
        self.calls.append((arguments, first_source_number))
        sources = tuple(
            Source(f"S{first_source_number + i}", f"Article {first_source_number + i}",
                   f"https://en.wikipedia.org/wiki/A{first_source_number + i}")
            for i in range(2)
        )  # fmt: skip
        return ToolOutcome(
            self.name,
            {"results": [{"source": s.id, "text": "..."} for s in sources]},
            ok=True,
            sources=sources,
        )


class FakeStats:
    name = "query_stats"

    def __init__(self, broken_definition: bool = False) -> None:
        self.broken = broken_definition
        self.calls: list[dict] = []

    def definition(self) -> dict:
        if self.broken:
            raise RuntimeError("stats database down")
        return {"type": "function", "function": {"name": self.name, "parameters": {}}}

    def call(self, arguments, **context) -> ToolOutcome:
        self.calls.append(arguments)
        if "drivers" in arguments.get("sql", ""):
            return ToolOutcome.error(self.name, "unknown table drivers")
        return ToolOutcome(self.name, {"columns": ["wins"], "rows": [[5]]}, ok=True)


class FakeResolver:
    def __init__(
        self, resolution: Resolution | None = None, error: Exception | None = None
    ):
        self.resolution, self.error = resolution, error

    def resolve(self, question: str) -> Resolution:
        if self.error:
            raise self.error
        return self.resolution or Resolution(question, (), ())


def orchestrator(llm, tools=None, resolver=None, **kwargs) -> Orchestrator:
    return Orchestrator(
        llm,  # type: ignore[arg-type]
        tools if tools is not None else [FakeStats(), FakeKnowledge()],
        resolver,  # type: ignore[arg-type]
        **kwargs,
    )


# --- the loop ---


def test_a_direct_answer_needs_one_request() -> None:
    llm = ScriptedLLM(reply("Formula 1 began in 1950."))

    answer = orchestrator(llm).answer("  When did F1 start? ")

    assert isinstance(answer, Answer)
    assert (
        answer.text == "Formula 1 began in 1950."
        and answer.question == "When did F1 start?"
    )
    assert (answer.sources, answer.tool_calls, answer.llm_calls) == ((), (), 1)
    (request,) = llm.requests
    assert request["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert request["messages"][1] == {"role": "user", "content": "When did F1 start?"}
    assert [t["function"]["name"] for t in request["tools"]] == [
        "query_stats",
        "search_f1_knowledge",
    ]
    assert request["max_tokens"] == MAX_TOOL_ROUND_TOKENS


def test_tool_results_go_back_to_the_model_and_the_answer_cites_them() -> None:
    stats, knowledge = FakeStats(), FakeKnowledge()
    llm = ScriptedLLM(
        reply(
            None,
            call("query_stats", 1, sql="SELECT wins FROM v_driver_career"),
            call("search_f1_knowledge", 2, query="Monza"),
        ),
        reply("Hamilton and Schumacher share it with 5 [S2]."),
    )

    answer = orchestrator(llm, [stats, knowledge]).answer("Most wins at Monza?")

    assert answer.text == "Hamilton and Schumacher share it with 5 [S2]."
    assert [s.id for s in answer.sources] == ["S2"]  # only the cited source
    assert [(r.name, r.ok) for r in answer.tool_calls] == [
        ("query_stats", True),
        ("search_f1_knowledge", True),
    ]
    assert (answer.llm_calls, answer.prompt_tokens, answer.completion_tokens) == (
        2,
        200,
        40,
    )
    assert (answer.provider, answer.model) == ("groq", "openai/gpt-oss-120b")

    second = llm.requests[1]["messages"]
    assistant, stats_result, knowledge_result = second[2], second[3], second[4]
    assert assistant["role"] == "assistant" and assistant["content"] is None
    assert assistant["_provider"] == "groq"  # another provider gets it as text
    assert [c["function"]["name"] for c in assistant["tool_calls"]] == [
        "query_stats",
        "search_f1_knowledge",
    ]
    assert json.loads(assistant["tool_calls"][1]["function"]["arguments"]) == {
        "query": "Monza"
    }
    assert stats_result == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": json.dumps({"columns": ["wins"], "rows": [[5]]}),
    }
    assert knowledge_result["tool_call_id"] == "call_2"


def test_source_ids_keep_counting_across_searches() -> None:
    knowledge = FakeKnowledge()
    llm = ScriptedLLM(
        reply(None, call("search_f1_knowledge", 1, query="a")),
        reply(None, call("search_f1_knowledge", 2, query="b")),
        reply("A [S1] and B [S4]."),
    )

    answer = orchestrator(llm, [knowledge]).answer("q")

    assert [first for _, first in knowledge.calls] == [1, 3]
    assert [s.id for s in answer.sources] == ["S1", "S4"]
    assert answer.sources[1].url.endswith("/A4")


def test_tool_errors_are_passed_to_the_model_to_fix() -> None:
    llm = ScriptedLLM(
        reply(None, call("query_stats", 1, sql="SELECT * FROM drivers")),
        reply(None, call("query_stats", 2, sql="SELECT wins FROM v_driver_career")),
        reply("5 wins."),
    )

    answer = orchestrator(llm).answer("q")

    assert [(r.ok, r.error) for r in answer.tool_calls] == [
        (False, "unknown table drivers"),
        (True, None),
    ]
    error_message = llm.requests[1]["messages"][-1]
    assert json.loads(error_message["content"]) == {"error": "unknown table drivers"}


def test_an_unknown_tool_gets_an_error_message() -> None:
    llm = ScriptedLLM(reply(None, call("drop_tables", 1)), reply("Sorry."))

    answer = orchestrator(llm).answer("q")

    assert answer.tool_calls[0].ok is False
    assert "unknown tool 'drop_tables'" in answer.tool_calls[0].error


def test_after_the_last_round_it_must_answer_without_tools() -> None:
    llm = ScriptedLLM(
        reply(None, call("search_f1_knowledge", 1, query="a")),
        reply(None, call("search_f1_knowledge", 2, query="b")),
        reply("From what I found: A [S1]."),
    )

    answer = orchestrator(llm, [FakeKnowledge()], max_rounds=2).answer("q")

    final = llm.requests[-1]
    assert final["tools"] is None and final["max_tokens"] == MAX_ANSWER_TOKENS
    assert final["messages"][-1] == {"role": "user", "content": FINAL_ROUND_NOTE}
    assert answer.llm_calls == 3 and answer.text == "From what I found: A [S1]."


def test_the_tool_call_limit_is_enforced() -> None:
    knowledge = FakeKnowledge()
    llm = ScriptedLLM(
        reply(
            None, *[call("search_f1_knowledge", i, query=str(i)) for i in range(1, 4)]
        ),
        reply("Done."),
    )

    answer = orchestrator(llm, [knowledge], max_tool_calls=2).answer("q")

    assert len(knowledge.calls) == 2 and len(answer.tool_calls) == 2
    tool_messages = [m for m in llm.requests[1]["messages"] if m["role"] == "tool"]
    assert len(tool_messages) == 3  # every call gets a reply, the third an error
    assert "limit reached" in tool_messages[-1]["content"]
    assert llm.requests[1]["tools"] is None  # limit reached: no more tools offered


def test_a_tool_that_cannot_describe_itself_is_left_out(caplog) -> None:
    llm = ScriptedLLM(reply("ok"))

    orchestrator(llm, [FakeStats(broken_definition=True), FakeKnowledge()]).answer("q")

    assert [t["function"]["name"] for t in llm.requests[0]["tools"]] == [
        "search_f1_knowledge"
    ]
    assert "Tool query_stats unavailable: RuntimeError" in caplog.text


def test_with_no_tools_available_it_answers_plainly() -> None:
    llm = ScriptedLLM(reply("I can't look that up right now."))

    answer = orchestrator(llm, [FakeStats(broken_definition=True)]).answer("q")

    assert llm.requests[0]["tools"] is None and answer.text.startswith("I can't")


# --- names ---


def _mention(text: str, *entities: Entity) -> Mention:
    return Mention(
        text, text.lower(), 0, len(text),
        tuple(Candidate(e, "surname", i == 0) for i, e in enumerate(entities)),
    )  # fmt: skip


HUNT = Entity("driver", 231, "hunt", "James Hunt", frozenset({1973, 1979}), 10, 92)
HILL_D = Entity(
    "driver", 712, "damon_hill", "Damon Hill", frozenset({1992, 1999}), 22, 116
)
HILL_G = Entity("driver", 277, "hill", "Graham Hill", frozenset({1958, 1975}), 14, 177)
MONZA = Entity(
    "circuit",
    7,
    "monza",
    "Autodromo Nazionale di Monza",
    frozenset({1950, 2025}),
    0,
    75,
)


def test_entity_hints_give_refs_and_alternatives() -> None:
    resolution = Resolution(
        "q",
        (1996,),
        (
            _mention("Hunt", HUNT),
            _mention("Hill", HILL_D, HILL_G),
            _mention("Monza", MONZA),
        ),
    )

    hints = entity_hints(resolution)

    assert hints == (
        "Names found in the question (best guess first):\n"
        "- \"Hunt\": driver James Hunt (driver_ref = 'hunt', 1973–1979).\n"
        "- \"Hill\": driver Damon Hill (driver_ref = 'damon_hill', 1992–1999). "
        "Could also be: driver Graham Hill (driver_ref = 'hill', 1958–1975).\n"
        '- "Monza": circuit Autodromo Nazionale di Monza '
        "(circuit_name = 'Autodromo Nazionale di Monza', races 1950–2025)."
    )
    assert user_message("Hunt?", resolution).startswith("Hunt?\n\nNames found")


def test_no_names_means_the_question_alone() -> None:
    assert entity_hints(None) is None
    assert user_message("Who won?", Resolution("Who won?", (), ())) == "Who won?"


def test_hints_reach_the_model_and_the_answer() -> None:
    resolution = Resolution("Hunt 1976", (1976,), (_mention("Hunt", HUNT),))
    llm = ScriptedLLM(reply("Hunt won."))

    answer = orchestrator(llm, resolver=FakeResolver(resolution)).answer("Hunt 1976")

    assert "driver_ref = 'hunt'" in llm.requests[0]["messages"][1]["content"]
    assert answer.resolution is resolution


def test_a_failing_resolver_does_not_stop_the_answer(caplog) -> None:
    llm = ScriptedLLM(reply("ok"))

    answer = orchestrator(llm, resolver=FakeResolver(error=SearchError("down"))).answer(
        "Hunt"
    )

    assert answer.resolution is None
    assert llm.requests[0]["messages"][1]["content"] == "Hunt"
    assert "Entity resolution skipped" in caplog.text


# --- failures ---


def test_an_llm_outage_is_a_safe_error() -> None:
    llm = ScriptedLLM(
        LLMUnavailableError("The language model is unavailable right now")
    )

    with pytest.raises(AnswerUnavailableError, match="unavailable right now") as info:
        orchestrator(llm).answer("q")
    assert info.value.__cause__ is None


def test_an_outage_mid_answer_is_a_safe_error() -> None:
    llm = ScriptedLLM(
        reply(None, call("query_stats", 1, sql="SELECT wins FROM v_driver_career")),
        LLMUnavailableError("The language model is unavailable right now"),
    )

    with pytest.raises(AnswerUnavailableError):
        orchestrator(llm).answer("q")


@pytest.mark.parametrize("content", ["", "   ", "[S9]", None])
def test_an_empty_answer_is_an_error(content) -> None:
    with pytest.raises(AnswerUnavailableError, match="empty answer"):
        orchestrator(ScriptedLLM(reply(content))).answer("q")


@pytest.mark.parametrize("bad", ["", "   ", "x" * 501])
def test_bad_questions_are_rejected_before_any_request(bad: str) -> None:
    llm = ScriptedLLM()

    with pytest.raises(ValueError):
        orchestrator(llm).answer(bad)
    assert llm.requests == []


def test_a_truncated_round_is_logged(caplog) -> None:
    orchestrator(ScriptedLLM(reply("Partial answ", finish="length"))).answer("q")

    assert "hit max_tokens" in caplog.text


# --- citations ---

KNOWN = {f"S{i}": Source(f"S{i}", f"T{i}", f"https://x/{i}") for i in range(1, 4)}


@pytest.mark.parametrize(
    ("text", "clean", "cited"),
    [
        ("Hunt won [S2].", "Hunt won [S2].", ["S2"]),
        ("A [S1] B [S1] C [S3].", "A [S1] B [S1] C [S3].", ["S1", "S3"]),
        ("Made up [S9].", "Made up.", []),
        ("Mixed [S2][S7].", "Mixed [S2].", ["S2"]),
        (
            "Grouped [S1, S3] and [S2; S9].",
            "Grouped [S1][S3] and [S2].",
            ["S1", "S3", "S2"],
        ),
        (
            "Full width【S3】 and 【S2†L10-L12】.",
            "Full width[S3] and [S2].",
            ["S3", "S2"],
        ),
        ("Suffix [S1†L2].", "Suffix [S1].", ["S1"]),
        ("No citations here.", "No citations here.", []),
        (
            "Keep [link](https://x) and [note].",
            "Keep [link](https://x) and [note].",
            [],
        ),
    ],
)
def test_citations_are_checked(text: str, clean: str, cited: list[str]) -> None:
    out, sources = clean_citations(text, KNOWN)

    assert out == clean
    assert [s.id for s in sources] == cited


# --- CLI ---


def test_cli_prints_the_answer_sources_and_trace(monkeypatch, capsys) -> None:
    answer = Answer(
        question="q", text="Hunt won [S1].",
        sources=(Source("S1", "1976 Japanese Grand Prix", "https://en.wikipedia.org/wiki/1976", "Race"),),
        tool_calls=(), resolution=None, provider="groq", model="m",
        prompt_tokens=10, completion_tokens=5, latency_ms=900, llm_calls=2,
    )  # fmt: skip

    class Fake:
        def answer(self, question):
            return answer

    monkeypatch.setattr(cli, "get_settings", lambda: make_settings())
    monkeypatch.setattr(cli, "build_orchestrator", lambda settings: Fake())

    assert cli.run(["How did Hunt win?", "--trace"]) == 0

    out = capsys.readouterr().out
    assert out.startswith("Hunt won [S1].")
    assert (
        "[S1] 1976 Japanese Grand Prix > Race — https://en.wikipedia.org/wiki/1976"
        in out
    )
    assert "groq · m · 2 LLM calls · 10+5 tokens · 900 ms" in out


def test_cli_errors(monkeypatch, capsys) -> None:
    class Down:
        def answer(self, question):
            raise AnswerUnavailableError("The language model is unavailable right now")

    monkeypatch.setattr(cli, "get_settings", lambda: make_settings())
    monkeypatch.setattr(cli, "build_orchestrator", lambda settings: Down())

    assert cli.run(["q"]) == 1
    assert "unavailable right now" in capsys.readouterr().err
    assert cli.run(["   "]) == 2


# --- streaming events (F4.1) ---


from app.answer.orchestrator import (  # noqa: E402
    CitationEvent,
    DoneEvent,
    TableEvent,
    TokenEvent,
    ToolEvent,
)
from app.llm.errors import LLMStreamInterruptedError  # noqa: E402


def test_events_arrive_in_order_ending_with_done() -> None:
    llm = ScriptedLLM(
        reply(
            None,
            call("query_stats", 1, sql="SELECT wins FROM v_driver_career"),
            call("search_f1_knowledge", 2, query="Monza"),
        ),
        reply("Hamilton and Schumacher share it [S1], 5 each [S2]."),
    )

    events = list(orchestrator(llm).stream("Most wins at Monza?"))

    kinds = [type(e).__name__ for e in events]
    assert kinds[:5] == [
        "ToolEvent",
        "ToolEvent",
        "TableEvent",
        "ToolEvent",
        "ToolEvent",
    ]
    assert kinds[-1] == "DoneEvent"
    assert [e.status for e in events if isinstance(e, ToolEvent)] == [
        "started", "finished", "started", "finished",
    ]  # fmt: skip
    table = next(e for e in events if isinstance(e, TableEvent))
    assert (table.columns, table.rows) == (("wins",), ((5,),))
    tokens = [e.text for e in events if isinstance(e, TokenEvent)]
    assert len(tokens) > 3  # streamed in pieces
    done = events[-1]
    assert isinstance(done, DoneEvent) and "".join(tokens).strip() == done.answer.text


def test_citations_are_events_when_first_cited() -> None:
    llm = ScriptedLLM(
        reply(None, call("search_f1_knowledge", 1, query="x")),
        reply("A [S2] then B [S1] and A again [S2]."),
    )

    events = list(orchestrator(llm, [FakeKnowledge()]).stream("q"))

    cited = [e.source.id for e in events if isinstance(e, CitationEvent)]
    assert cited == ["S2", "S1"]
    first_citation = next(
        i for i, e in enumerate(events) if isinstance(e, CitationEvent)
    )
    assert any(isinstance(e, TokenEvent) for e in events[:first_citation])
    assert events[-1].answer.sources == tuple(  # type: ignore[union-attr]
        e.source for e in events if isinstance(e, CitationEvent)
    )


def test_an_invalid_citation_never_reaches_the_stream() -> None:
    llm = ScriptedLLM(reply("Fact [S9]. Another【S7†L2】 fact."))

    tokens = [
        e.text for e in orchestrator(llm).stream("q") if isinstance(e, TokenEvent)
    ]

    streamed = "".join(tokens)
    assert "S9" not in streamed and "S7" not in streamed
    assert streamed == "Fact. Another fact."


def test_a_stream_interrupted_after_tokens_raises_after_them() -> None:
    llm = ScriptedLLM(
        (
            reply("never mind"),
            LLMStreamInterruptedError("The answer was interrupted; please try again"),
        )
    )

    received = []
    with pytest.raises(AnswerUnavailableError, match="interrupted"):
        for event in orchestrator(llm).stream("q"):
            received.append(event)

    assert [e.text for e in received if isinstance(e, TokenEvent)] == ["Partial"]


def test_bad_questions_fail_before_the_first_event() -> None:
    llm = ScriptedLLM()

    with pytest.raises(ValueError):
        orchestrator(llm).stream("   ")  # raised on the call, not on iteration
    assert llm.requests == []


def test_provider_extras_are_echoed_back_with_the_tool_call() -> None:
    signed = ToolCall("call_1", "search_f1_knowledge", {"query": "x"},
                      {"extra_content": {"google": {"thought_signature": "sig"}}})  # fmt: skip
    llm = ScriptedLLM(reply(None, signed), reply("Done [S1]."))

    orchestrator(llm, [FakeKnowledge()]).answer("q")

    (tool_call,) = llm.requests[1]["messages"][2]["tool_calls"]
    assert tool_call["extra_content"] == {"google": {"thought_signature": "sig"}}


def test_close_disposes_tools_that_hold_resources() -> None:
    class Pooled(FakeKnowledge):
        disposed = False

        def dispose(self) -> None:
            self.disposed = True

    tool = Pooled()
    orchestrator(ScriptedLLM(), [tool, FakeStats()]).close()

    assert tool.disposed


# --- the streaming citation filter gives the same result whatever the chunks ---

from app.answer.orchestrator import CitationFilter  # noqa: E402

STREAM_CASES = [
    "Hunt won [S2].",
    "Lauda crashed【S3】. Hunt won【S2†L4-L9】 and [S1†L2].",
    "Grouped [S1, S3] and [S2; S9].",
    "Made up [S9]. Real [S2].",
    "fact [S9] more",
    "x [S9]y",
    "Keep [link](https://x) and [note].",
    "  - item\n    - nested [S1]\n",
    "an unclosed [ bracket that runs on for long enough to stop waiting",
    "end [S2]",
]


def _stream(text: str, size: int) -> str:
    citations = CitationFilter(KNOWN)
    parts = [citations.feed(text[i : i + size])[0] for i in range(0, len(text), size)]
    parts.append(citations.flush()[0])
    return "".join(parts).strip()


@pytest.mark.parametrize("text", STREAM_CASES)
@pytest.mark.parametrize("size", [1, 2, 3, 7])
def test_streaming_matches_the_whole_text(text: str, size: int) -> None:
    assert _stream(text, size) == clean_citations(text, KNOWN)[0]


def test_a_dropped_marker_at_a_chunk_boundary_keeps_the_space() -> None:
    citations = CitationFilter(KNOWN)
    first, _ = citations.feed("fact [S9]")
    second, _ = citations.feed("more")
    rest, _ = citations.flush()

    assert first + second + rest == "fact more"


def test_nested_list_indentation_survives() -> None:
    text, _ = clean_citations("- a\n    - b [S1]\n        - c", KNOWN)

    assert text == "- a\n    - b [S1]\n        - c"
