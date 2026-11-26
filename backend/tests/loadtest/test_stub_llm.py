"""The stub LLM (F6.4): what it answers, and that our real LLM client can use it."""

import json

import openai
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.llm.client import LLMClient
from app.llm.providers import Provider
from loadtest.stub_llm import (
    KNOWLEDGE_TOOL,
    STATS_SQL,
    STATS_TOOL,
    Delays,
    create_app,
    plan,
    question_of,
    split,
)

FAST = Delays(tool_ms=0, first_token_ms=0, token_ms=0, tokens=5)
TOOLS = [
    {"type": "function", "function": {"name": STATS_TOOL}},
    {"type": "function", "function": {"name": KNOWLEDGE_TOOL}},
]


def _user(text: str) -> dict:
    return {"role": "user", "content": text}


def test_question_of_skips_entity_hints_and_reads_the_condenser_message() -> None:
    assert question_of([_user("Explain Abu Dhabi 2021\n\nNames: …")]) == (
        "Explain Abu Dhabi 2021"
    )
    condense = "<conversation>\nuser: hi\n</conversation>\n\nLast message: And him?"
    assert question_of([_user(condense)]) == "And him?"
    assert question_of([{"role": "system", "content": "x"}]) == ""


@pytest.mark.parametrize(
    ("question", "tool"),
    [
        ("Who has the most wins at Monza?", (STATS_TOOL, {"sql": STATS_SQL})),
        (
            "Explain Abu Dhabi 2021",
            (KNOWLEDGE_TOOL, {"query": "Explain Abu Dhabi 2021"}),
        ),
    ],
)
def test_a_first_round_calls_a_tool(question: str, tool: tuple) -> None:
    body = {"stream": True, "tools": TOOLS, "messages": [_user(question)]}
    assert plan(body) == ("tool", tool)


def test_after_a_tool_result_it_answers_with_a_citation() -> None:
    for result in (
        {"role": "tool", "tool_call_id": "c", "content": "{}"},
        _user("Result of search_f1_knowledge (tool output): …"),  # flattened history
    ):
        body = {"stream": True, "tools": TOOLS, "messages": [_user("Q?"), result]}
        assert plan(body) == ("text", "Stub answer to: Q? [S1]")


def test_without_tools_or_streaming() -> None:
    assert plan({"stream": True, "messages": [_user("Q?")]}) == (
        "text",
        "Stub answer to: Q?",
    )
    assert plan({"messages": [_user("Q?")]}) == ("complete", "Q?")


def test_split_joins_back_exactly() -> None:
    text = "Stub answer to: Explain Abu Dhabi 2021 [S1]"
    for pieces in (1, 5, 40, 500):
        assert "".join(split(text, pieces)) == text
    assert len(split(text, 5)) == 5


def test_delays_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUB_TOOL_DELAY_MS", "50")
    monkeypatch.setenv("STUB_TOKENS", " ")
    assert Delays.from_env() == Delays(tool_ms=50, tokens=40)
    monkeypatch.setenv("STUB_TOKEN_MS", "-1")
    with pytest.raises(ValueError, match="STUB_TOKEN_MS"):
        Delays.from_env()


def _events(body: str) -> list[dict]:
    return [
        json.loads(line[6:])
        for line in body.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]


def test_streams_a_tool_call_then_usage() -> None:
    client = TestClient(create_app(FAST))
    response = client.post(
        "/v1/chat/completions",
        json={"stream": True, "tools": TOOLS, "messages": [_user("Explain 1976")]},
    )
    assert response.status_code == 200
    assert response.text.rstrip().endswith("data: [DONE]")
    events = _events(response.text)
    call = events[1]["choices"][0]["delta"]["tool_calls"][0]
    assert call["function"]["name"] == KNOWLEDGE_TOOL
    assert json.loads(call["function"]["arguments"]) == {"query": "Explain 1976"}
    assert events[2]["choices"][0]["finish_reason"] == "tool_calls"
    assert events[-1]["usage"]["prompt_tokens"] == 3000
    assert client.get("/health").json()["requests"] == 1


@pytest.mark.parametrize("body", ["not json", "[1, 2]", '{"messages": []}'])
def test_bad_requests(body: str) -> None:
    response = TestClient(create_app(FAST)).post(
        "/v1/chat/completions",
        content=body,
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400


def _llm_against_stub() -> LLMClient:
    """Our real client, its openai SDK routed into the stub app in-process."""
    stub = create_app(FAST)

    def factory(**kwargs: object) -> openai.OpenAI:
        return openai.OpenAI(
            **kwargs, http_client=TestClient(stub, base_url="http://stub")
        )

    return LLMClient(
        [Provider("groq", "http://stub/v1", "stub-model", SecretStr("k"))],
        timeout=5,
        max_retries=0,
        rate_limit_wait_seconds=0,
        client_factory=factory,
    )


def test_our_client_gets_a_tool_call_then_text_from_the_stub() -> None:
    llm = _llm_against_stub()
    tools = [
        {
            "type": "function",
            "function": {
                "name": KNOWLEDGE_TOOL,
                "description": "search",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            },
        }
    ]
    messages = [{"role": "user", "content": "Explain Abu Dhabi 2021"}]

    turn = llm.stream_turn(messages, tools=tools)
    assert [c.name for c in turn.tool_calls] == [KNOWLEDGE_TOOL]
    assert turn.tool_calls[0].arguments == {"query": "Explain Abu Dhabi 2021"}

    messages += [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": turn.tool_calls[0].id,
                    "type": "function",
                    "function": {"name": KNOWLEDGE_TOOL, "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": turn.tool_calls[0].id, "content": "{}"},
    ]
    turn = llm.stream_turn(messages, tools=tools)
    assert "".join(turn) == "Stub answer to: Explain Abu Dhabi 2021 [S1]"
    assert turn.usage is not None and turn.usage.prompt_tokens == 3000

    response = llm.complete(
        [_user("<conversation>…</conversation>\n\nLast message: Q?")]
    )
    assert response.content == "Q?"
