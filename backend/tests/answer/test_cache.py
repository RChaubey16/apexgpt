"""The answer cache (F4.4): keys, LRU, TTL, and the orchestrator's use of it."""

import threading

import pytest

from app.answer.cache import AnswerCache, cache_key, coalesce
from app.answer.followups import HistoryMessage
from app.answer.orchestrator import (
    AnswerUnavailableError,
    CitationEvent,
    DoneEvent,
    QuestionEvent,
    TableEvent,
    TokenEvent,
    ToolEvent,
)
from tests.answer.test_orchestrator import (
    CondensingLLM,
    FakeKnowledge,
    FakeStats,
    ScriptedLLM,
    call,
    orchestrator,
    reply,
)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


# --- keys ---


@pytest.mark.parametrize(
    "variant",
    [
        "Who won in 2005?",
        "who won in 2005",
        "  WHO   won in\t2005 ?? ",
        "Who won in 2005!",
        "Who won in 2005？",  # full-width question mark (NFKC)
        "Ｗho won in 2005",  # full-width letter
    ],
)
def test_variants_of_a_question_share_a_key(variant: str) -> None:
    assert cache_key(variant) == "who won in 2005"


def test_different_questions_have_different_keys() -> None:
    assert cache_key("Who won in 2005?") != cache_key("Who won in 2006?")
    assert cache_key("Who won at Monza?") != cache_key("Who won at Monza in 1988?")


# --- the cache ---


def test_lru_evicts_the_least_recently_used() -> None:
    cache = AnswerCache(size=2, ttl_seconds=60)
    cache.put("a", (1,))
    cache.put("b", (2,))
    assert cache.get("a") == (1,)  # a is now the most recent

    cache.put("c", (3,))

    assert (cache.get("a"), cache.get("b"), cache.get("c")) == ((1,), None, (3,))
    assert len(cache) == 2


def test_entries_expire() -> None:
    clock = Clock()
    cache = AnswerCache(size=2, ttl_seconds=60, clock=clock)
    cache.put("a", (1,))

    clock.now = 59.9
    assert cache.get("a") == (1,)
    clock.now = 60.0
    assert cache.get("a") is None
    assert len(cache) == 0  # an expired entry is dropped


def test_put_replaces_and_refreshes() -> None:
    clock = Clock()
    cache = AnswerCache(size=2, ttl_seconds=60, clock=clock)
    cache.put("a", (1,))
    clock.now = 50
    cache.put("a", (2,))
    clock.now = 100

    assert cache.get("a") == (2,)


def test_size_must_be_positive() -> None:
    with pytest.raises(ValueError):
        AnswerCache(size=0, ttl_seconds=60)


def test_concurrent_use_keeps_the_bound() -> None:
    cache = AnswerCache(size=50, ttl_seconds=60)

    def work(n: int) -> None:
        for i in range(500):
            cache.put(f"{n}-{i}", (i,))
            cache.get(f"{n}-{i // 2}")

    threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(cache) == 50


def test_coalesce_merges_token_runs_only() -> None:
    events = [TokenEvent("a"), TokenEvent("b"), CitationEvent(None), TokenEvent("c"),  # type: ignore[arg-type]
              TokenEvent("d"), ToolEvent("x", "started")]  # fmt: skip

    assert coalesce(events, TokenEvent) == (
        TokenEvent("ab"),
        CitationEvent(None),  # type: ignore[arg-type]
        TokenEvent("cd"),
        ToolEvent("x", "started"),
    )


# --- in the orchestrator ---


def knowledge_answer() -> list:
    return [
        reply(None, call("search_f1_knowledge", 1, query="Abu Dhabi 2021")),
        reply("Verstappen won the title [S1]."),
    ]


def test_a_repeated_question_is_replayed_without_llm_or_tools() -> None:
    knowledge = FakeKnowledge()
    llm = ScriptedLLM(*knowledge_answer())
    orch = orchestrator(
        llm, [FakeStats(), knowledge], cache=AnswerCache(size=8, ttl_seconds=60)
    )

    first = list(orch.stream("Explain Abu Dhabi 2021"))
    second = list(orch.stream("explain abu dhabi 2021?"))

    assert len(llm.requests) == 2 and len(knowledge.calls) == 1  # first time only

    # The same events, tokens merged into one.
    def content(events):
        return [e for e in events if not isinstance(e, (TokenEvent, DoneEvent))]

    assert content(second) == content(first)

    def text(events):
        return "".join(e.text for e in events if isinstance(e, TokenEvent))

    assert text(second) == text(first) == "Verstappen won the title [S1]."
    assert sum(isinstance(e, TokenEvent) for e in second) == 1
    done_first, done_second = first[-1].answer, second[-1].answer
    assert not done_first.cached and done_second.cached
    assert done_second.question == "explain abu dhabi 2021?"
    assert (done_second.prompt_tokens, done_second.completion_tokens,
            done_second.llm_calls) == (0, 0, 0)  # fmt: skip
    assert (done_second.text, done_second.sources, done_second.provider,
            done_second.tool_calls) == (done_first.text, done_first.sources,
                                        done_first.provider, done_first.tool_calls)  # fmt: skip


def test_without_a_cache_every_question_is_answered() -> None:
    llm = ScriptedLLM(reply("One."), reply("Two."))
    orch = orchestrator(llm)

    assert orch.answer("q").text == "One."
    assert orch.answer("q").text == "Two."


def test_a_failed_tool_call_is_not_cached() -> None:
    llm = ScriptedLLM(
        reply(None, call("query_stats", 1, sql="SELECT * FROM drivers")),
        reply("I couldn't look that up."),
        reply("Five wins."),
    )
    cache = AnswerCache(size=8, ttl_seconds=60)
    orch = orchestrator(llm, cache=cache)

    orch.answer("Most wins at Monza?")
    assert len(cache) == 0
    assert orch.answer("Most wins at Monza?").text == "Five wins."
    assert len(cache) == 1


def test_an_answer_with_a_tool_missing_is_not_cached() -> None:
    cache = AnswerCache(size=8, ttl_seconds=60)
    orch = orchestrator(
        ScriptedLLM(reply("Plain answer.")),
        [FakeStats(broken_definition=True), FakeKnowledge()],
        cache=cache,
    )

    orch.answer("q")

    assert len(cache) == 0


def test_an_answer_that_fails_or_is_abandoned_is_not_cached() -> None:
    from app.llm.errors import LLMStreamInterruptedError

    cache = AnswerCache(size=8, ttl_seconds=60)
    llm = ScriptedLLM((reply("x"), LLMStreamInterruptedError("cut")), reply("Full."))
    orch = orchestrator(llm, cache=cache)

    with pytest.raises(AnswerUnavailableError):
        list(orch.stream("q"))
    stream = orch.stream("q")
    next(stream)  # the client goes away after the first event
    stream.close()

    assert len(cache) == 0


def test_a_follow_up_uses_the_cache_of_its_standalone_question() -> None:
    cache = AnswerCache(size=8, ttl_seconds=60)
    first = orchestrator(ScriptedLLM(reply("Senna took 13 poles.")), cache=cache)
    first.answer("How many poles did Ayrton Senna get in 1988?")

    llm = CondensingLLM("How many poles did Ayrton Senna get in 1988?")
    events = list(
        orchestrator(llm, cache=cache).stream(
            "How many did he get?",
            [
                HistoryMessage("user", "Who won 1988?"),
                HistoryMessage("assistant", "Senna."),
            ],
        )
    )

    assert events[0] == QuestionEvent("How many poles did Ayrton Senna get in 1988?")
    answer = events[-1].answer
    assert answer.cached and answer.text == "Senna took 13 poles."
    assert answer.asked == "How many did he get?"
    assert answer.llm_calls == 1  # the condense request only
    assert (answer.prompt_tokens, answer.completion_tokens) == (100, 20)
    assert llm.requests == []


def test_tables_are_replayed() -> None:
    cache = AnswerCache(size=8, ttl_seconds=60)
    llm = ScriptedLLM(
        reply(None, call("query_stats", 1, sql="SELECT wins")), reply("Five.")
    )
    orch = orchestrator(llm, cache=cache)
    orch.answer("q")

    replayed = list(orch.stream("q"))

    assert TableEvent(("wins",), ((5,),)) in replayed


def test_the_app_builds_the_cache_from_settings() -> None:
    from app.main import create_app
    from tests.conftest import make_settings

    default = create_app(make_settings(environment="test")).state.orchestrator
    off = create_app(
        make_settings(environment="test", answer_cache_size=0)
    ).state.orchestrator

    assert isinstance(default._cache, AnswerCache)
    assert off._cache is None
