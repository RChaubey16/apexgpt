"""LLMClient: fallback, retries, validation and streaming, with a fake openai client."""

from collections.abc import Iterator
from typing import Any

import httpx2
import openai
import pytest
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from pydantic import SecretStr

from app.llm.client import (
    BACKOFF_SECONDS,
    MAX_PROMPT_CHARS,
    MAX_TOKENS_LIMIT,
    LLMClient,
)
from app.llm.errors import LLMStreamInterruptedError, LLMUnavailableError
from app.llm.providers import Provider

REQUEST = httpx2.Request("POST", "https://llm.example.invalid/v1/chat/completions")
USER = [{"role": "user", "content": "Who won in 1976?"}]
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_f1_knowledge",
            "description": "Search F1 history.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }
]


def provider(name: str) -> Provider:
    return Provider(
        name,
        f"https://{name}.example.invalid/v1",
        f"{name}-model",
        SecretStr(f"key-{name}-secret"),
    )


def status_error(cls: type[openai.APIStatusError], code: int) -> openai.APIStatusError:
    return cls(
        "provider said no", response=httpx2.Response(code, request=REQUEST), body=None
    )


def completion(
    content: str | None = "James Hunt.",
    tool_calls: list[dict] | None = None,
    usage: bool = True,
    finish_reason: str = "stop",
) -> ChatCompletion:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    data: dict[str, Any] = {
        "id": "c1",
        "object": "chat.completion",
        "created": 0,
        "model": "m",
        "choices": [{"index": 0, "finish_reason": finish_reason, "message": message}],
    }
    if usage:
        data["usage"] = {
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "total_tokens": 18,
        }
    return ChatCompletion.model_validate(data)


def tool_call(
    name: str = "search_f1_knowledge", arguments: str = '{"query": "1976"}'
) -> dict:
    return {
        "id": "call_1",
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def chunk(text: str | None) -> ChatCompletionChunk:
    return ChatCompletionChunk.model_validate(
        {
            "id": "k",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "m",
            "choices": [
                {"index": 0, "delta": {"content": text}, "finish_reason": None}
            ],
        }
    )


class FakeStream:
    def __init__(self, items: list[Any]) -> None:
        self.items, self.closed = items, False

    def __iter__(self) -> Iterator[Any]:
        for item in self.items:
            if isinstance(item, BaseException):
                raise item
            yield item

    def close(self) -> None:
        self.closed = True


class FakeProviders:
    """openai.OpenAI stand-in: each provider answers from its own script."""

    def __init__(self, scripts: dict[str, list[Any]]) -> None:
        self.scripts = scripts
        self.created: list[dict] = []
        self.requests: list[tuple[str, dict]] = []

    def __call__(self, **kwargs: Any) -> Any:
        self.created.append(kwargs)
        name = kwargs["base_url"].split("//")[1].split(".")[0]
        fake = self

        class Completions:
            def create(self, **request: Any) -> Any:
                fake.requests.append((name, request))
                outcome = fake.scripts[name].pop(0)
                if isinstance(outcome, BaseException):
                    raise outcome
                return outcome

        class Chat:
            completions = Completions()

        class Client:
            chat = Chat()

        return Client()

    def calls(self) -> list[str]:
        return [name for name, _ in self.requests]


def make(
    scripts: dict[str, list[Any]],
    *,
    retries: int = 1,
    order=("groq", "gemini", "openrouter"),
):
    fake = FakeProviders(scripts)
    sleeps: list[float] = []
    client = LLMClient(
        [provider(n) for n in order if n in scripts],
        timeout=12.5,
        max_retries=retries,
        client_factory=fake,
        sleep=sleeps.append,
    )
    return client, fake, sleeps


# --- complete: success and request shape ---


def test_first_provider_answers() -> None:
    client, fake, sleeps = make({"groq": [completion()], "gemini": []})

    response = client.complete(USER)

    assert response.content == "James Hunt."
    assert (response.provider, response.model) == ("groq", "groq-model")
    assert response.usage is not None and response.usage.prompt_tokens == 11
    assert response.finish_reason == "stop" and response.tool_calls == ()
    assert response.latency_ms >= 0
    assert fake.calls() == ["groq"] and sleeps == []


def test_sdk_clients_get_the_key_url_timeout_and_no_sdk_retries() -> None:
    client, fake, _ = make({"groq": [completion(), completion()]})

    client.complete(USER)
    client.complete(USER)

    assert fake.created == [  # created once, reused
        {
            "api_key": "key-groq-secret",
            "base_url": "https://groq.example.invalid/v1",
            "timeout": 12.5,
            "max_retries": 0,
        }
    ]


def test_request_parameters() -> None:
    client, fake, _ = make(
        {"groq": [completion(), completion(tool_calls=[tool_call()])]}
    )

    client.complete(USER, temperature=0.0, max_tokens=50)
    client.complete(USER, tools=TOOLS, tool_choice="required")

    _, plain = fake.requests[0]
    assert plain == {
        "model": "groq-model",
        "messages": USER,
        "temperature": 0.0,
        "max_tokens": 50,
    }
    _, with_tools = fake.requests[1]
    assert with_tools["tools"] == TOOLS and with_tools["tool_choice"] == "required"


def test_tool_calls_are_parsed() -> None:
    client, _, _ = make(
        {
            "groq": [
                completion(
                    content=None, tool_calls=[tool_call()], finish_reason="tool_calls"
                )
            ]
        }
    )

    response = client.complete(USER, tools=TOOLS)

    (call,) = response.tool_calls
    assert (call.id, call.name, call.arguments) == (
        "call_1",
        "search_f1_knowledge",
        {"query": "1976"},
    )
    assert response.content is None and response.finish_reason == "tool_calls"


def test_missing_usage_is_allowed() -> None:
    client, _, _ = make({"groq": [completion(usage=False)]})

    assert client.complete(USER).usage is None


# --- complete: fallback and retries ---


def test_rate_limit_falls_back_at_once_without_retrying() -> None:
    client, fake, sleeps = make(
        {"groq": [status_error(openai.RateLimitError, 429)], "gemini": [completion()]}
    )

    response = client.complete(USER)

    assert response.provider == "gemini"
    assert fake.calls() == ["groq", "gemini"] and sleeps == []


@pytest.mark.parametrize(
    "error",
    [
        openai.APITimeoutError(request=REQUEST),
        openai.APIConnectionError(request=REQUEST),
        status_error(openai.InternalServerError, 500),
        status_error(openai.APIStatusError, 503),
    ],
    ids=["timeout", "connection", "500", "503"],
)
def test_transient_errors_retry_the_same_provider(error: Exception) -> None:
    client, fake, sleeps = make({"groq": [error, completion()], "gemini": []})

    assert client.complete(USER).provider == "groq"
    assert fake.calls() == ["groq", "groq"]
    assert sleeps == [BACKOFF_SECONDS[0]]


def test_retries_run_out_then_the_next_provider_is_tried() -> None:
    timeout = openai.APITimeoutError(request=REQUEST)
    client, fake, sleeps = make(
        {"groq": [timeout, timeout, timeout], "gemini": [completion()]}, retries=2
    )

    assert client.complete(USER).provider == "gemini"
    assert fake.calls() == ["groq", "groq", "groq", "gemini"]
    assert sleeps == [BACKOFF_SECONDS[0], BACKOFF_SECONDS[1]]


def test_no_retries_when_disabled() -> None:
    client, fake, sleeps = make(
        {"groq": [openai.APITimeoutError(request=REQUEST)], "gemini": [completion()]},
        retries=0,
    )

    assert client.complete(USER).provider == "gemini"
    assert fake.calls() == ["groq", "gemini"] and sleeps == []


@pytest.mark.parametrize(
    ("cls", "code"),
    [
        (openai.AuthenticationError, 401),
        (openai.PermissionDeniedError, 403),
        (openai.NotFoundError, 404),  # retired model
        (openai.BadRequestError, 400),  # e.g. Groq's tool_use_failed
        (openai.UnprocessableEntityError, 422),
    ],
)
def test_other_api_errors_fall_back_without_retrying(cls: type, code: int) -> None:
    client, fake, sleeps = make(
        {"groq": [status_error(cls, code)], "gemini": [completion()]}
    )

    assert client.complete(USER).provider == "gemini"
    assert fake.calls() == ["groq", "gemini"] and sleeps == []


def test_the_whole_chain_is_tried_in_order() -> None:
    client, fake, _ = make(
        {
            "groq": [status_error(openai.RateLimitError, 429)],
            "gemini": [status_error(openai.AuthenticationError, 401)],
            "openrouter": [completion()],
        }
    )

    assert client.complete(USER).provider == "openrouter"
    assert fake.calls() == ["groq", "gemini", "openrouter"]


def test_every_provider_failing_is_a_safe_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, _, _ = make(
        {
            "groq": [status_error(openai.RateLimitError, 429)],
            "gemini": [status_error(openai.InternalServerError, 500)] * 2,
        }
    )

    with pytest.raises(LLMUnavailableError, match="unavailable right now") as info:
        client.complete([{"role": "user", "content": "my private question"}])

    assert info.value.__cause__ is None
    assert (
        "provider=groq" in caplog.text
        and "error=RateLimitError status=429" in caplog.text
    )
    assert "provider=gemini" in caplog.text and "attempt=2" in caplog.text
    for secret in (
        "key-groq-secret",
        "key-gemini-secret",
        "my private question",
        "provider said no",
    ):
        assert secret not in caplog.text


def test_no_providers_configured() -> None:
    client = LLMClient([], client_factory=FakeProviders({}))

    with pytest.raises(LLMUnavailableError, match="GROQ_API_KEY"):
        client.complete(USER)
    assert client.provider_names == []


def test_unexpected_exceptions_are_not_swallowed() -> None:
    client, fake, _ = make({"groq": [KeyError("bug")], "gemini": [completion()]})

    with pytest.raises(KeyError):
        client.complete(USER)
    assert fake.calls() == ["groq"]


# --- complete: unusable responses fall back ---


@pytest.mark.parametrize(
    "bad",
    [
        completion(content=None),
        completion(content="   "),
        completion(content=None, tool_calls=[tool_call(name="drop_tables")]),
        completion(content=None, tool_calls=[tool_call(arguments="{not json")]),
        completion(content=None, tool_calls=[tool_call(arguments='["a list"]')]),
        ChatCompletion.model_validate(
            {
                "id": "x",
                "object": "chat.completion",
                "created": 0,
                "model": "m",
                "choices": [],
            }
        ),
    ],
    ids=[
        "no content",
        "blank content",
        "unknown tool",
        "bad json",
        "not an object",
        "no choices",
    ],
)
def test_unusable_responses_fall_back(
    bad: ChatCompletion, caplog: pytest.LogCaptureFixture
) -> None:
    client, fake, _ = make({"groq": [bad], "gemini": [completion()]})

    assert client.complete(USER, tools=TOOLS).provider == "gemini"
    assert fake.calls() == ["groq", "gemini"]
    assert "LLM response unusable: provider=groq" in caplog.text


def test_tool_calls_without_offered_tools_are_unusable() -> None:
    client, _, _ = make(
        {
            "groq": [completion(content=None, tool_calls=[tool_call()])],
            "gemini": [completion()],
        }
    )

    assert client.complete(USER).provider == "gemini"


def test_empty_tool_arguments_mean_an_empty_object() -> None:
    client, _, _ = make(
        {"groq": [completion(content=None, tool_calls=[tool_call(arguments="")])]}
    )

    assert client.complete(USER, tools=TOOLS).tool_calls[0].arguments == {}


# --- request validation (before any call) ---


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"messages": []}, "at least one message"),
        ({"messages": [{"role": "robot", "content": "x"}]}, "role"),
        ({"messages": [{"role": "user", "content": 42}]}, "string"),
        ({"messages": [{"role": "user"}]}, "omit content"),
        ({"messages": [{"role": "tool", "content": "{}"}]}, "tool_call_id"),
        (
            {"messages": [{"role": "user", "content": "x" * (MAX_PROMPT_CHARS + 1)}]},
            "longer than",
        ),
        ({"tools": [{"type": "retrieval"}]}, "type"),
        (
            {"tools": [{"type": "function", "function": {"name": "bad name!"}}]},
            "tool names",
        ),
        ({"tools": TOOLS + TOOLS}, "duplicate"),
        (
            {
                "tools": [
                    {"type": "function", "function": {"name": "t", "parameters": "x"}}
                ]
            },
            "schema",
        ),
        ({"tool_choice": "auto"}, "needs tools"),
        ({"tools": TOOLS, "tool_choice": "always"}, "tool_choice"),
        ({"temperature": 2.5}, "temperature"),
        ({"max_tokens": 0}, "max_tokens"),
        ({"max_tokens": MAX_TOKENS_LIMIT + 1}, "max_tokens"),
    ],
)
def test_bad_requests_are_rejected_before_calling(kwargs: dict, message: str) -> None:
    client, fake, _ = make({"groq": [completion()]})
    messages = kwargs.pop("messages", USER)

    with pytest.raises(ValueError, match=message):
        client.complete(messages, **kwargs)
    assert fake.requests == []


def test_a_tool_conversation_is_valid() -> None:
    client, _, _ = make({"groq": [completion()]})
    messages = USER + [
        {"role": "assistant", "content": None, "tool_calls": [tool_call()]},
        {"role": "tool", "tool_call_id": "call_1", "content": '{"results": []}'},
    ]

    assert client.complete(messages, tools=TOOLS).content == "James Hunt."


# --- stream ---


def test_stream_yields_text_pieces_and_names_the_provider() -> None:
    raw = FakeStream([chunk(None), chunk("James "), chunk(""), chunk("Hunt.")])
    client, fake, _ = make({"groq": [raw]})

    stream = client.stream(USER, max_tokens=64)

    assert (stream.provider, stream.model) == ("groq", "groq-model")
    assert list(stream) == ["James ", "Hunt."]
    assert raw.closed
    _, request = fake.requests[0]
    assert request["stream"] is True and request["max_tokens"] == 64


def test_stream_falls_back_before_the_first_token() -> None:
    failing = FakeStream([chunk(None), openai.APIConnectionError(request=REQUEST)])
    client, fake, _ = make(
        {
            "groq": [status_error(openai.RateLimitError, 429)],
            "gemini": [failing, FakeStream([])],  # error before any text, then empty
            "openrouter": [FakeStream([chunk("Hunt.")])],
        }
    )

    stream = client.stream(USER)

    assert stream.provider == "openrouter"
    assert list(stream) == ["Hunt."]
    assert fake.calls() == ["groq", "gemini", "gemini", "openrouter"]
    assert failing.closed


def test_stream_failure_after_the_first_token_is_an_interruption(
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw = FakeStream([chunk("James "), openai.APIConnectionError(request=REQUEST)])
    client, fake, _ = make({"groq": [raw], "gemini": [FakeStream([chunk("never")])]})

    stream = client.stream(USER)
    pieces = []
    with pytest.raises(LLMStreamInterruptedError, match="interrupted") as info:
        for piece in stream:
            pieces.append(piece)

    assert pieces == ["James "]
    assert info.value.__cause__ is None
    assert fake.calls() == ["groq"]  # no restart elsewhere mid-answer
    assert raw.closed
    assert "LLM stream interrupted: provider=groq" in caplog.text


def test_stream_closes_when_the_reader_stops_early() -> None:
    raw = FakeStream([chunk("a"), chunk("b"), chunk("c")])
    client, _, _ = make({"groq": [raw]})

    pieces = iter(client.stream(USER))
    assert next(pieces) == "a"
    pieces.close()  # type: ignore[attr-defined]

    assert raw.closed


def test_stream_with_every_provider_failing() -> None:
    client, _, _ = make({"groq": [FakeStream([])]})

    with pytest.raises(LLMUnavailableError):
        client.stream(USER)


def test_stream_validates_the_request() -> None:
    client, fake, _ = make({"groq": [FakeStream([chunk("x")])]})

    with pytest.raises(ValueError, match="at least one message"):
        client.stream([])
    assert fake.requests == []


# --- rate limits: wait once when the limit resets soon ---


def rate_limited(headers: dict[str, str]) -> openai.RateLimitError:
    return openai.RateLimitError(
        "rate limited",
        response=httpx2.Response(429, request=REQUEST, headers=headers),
        body=None,
    )


@pytest.mark.parametrize(
    ("value", "seconds"),
    [("42", 42.0), ("1.5", 1.5), ("42.577s", 42.577), ("1m2.5s", 62.5), ("120ms", 0.12),
     ("2h", 7200.0), (None, None), ("", None), ("soon", None), ("5x", None)],
)  # fmt: skip
def test_parse_duration(value, seconds) -> None:
    from app.llm.client import parse_duration

    assert parse_duration(value) == (
        pytest.approx(seconds) if seconds is not None else None
    )


def test_a_short_rate_limit_is_waited_out_once() -> None:
    fake = FakeProviders({"groq": [rate_limited({"retry-after": "2"}), completion()]})
    sleeps: list[float] = []
    client = LLMClient(
        [provider("groq")],
        rate_limit_wait_seconds=20,
        client_factory=fake,
        sleep=sleeps.append,
    )

    assert client.complete(USER).provider == "groq"
    assert sleeps == [2.5]  # the reset plus a little margin
    assert fake.calls() == ["groq", "groq"]


def test_the_token_window_reset_is_used_without_retry_after() -> None:
    fake = FakeProviders(
        {"groq": [rate_limited({"x-ratelimit-reset-tokens": "7.2s"}), completion()]}
    )
    sleeps: list[float] = []
    LLMClient(
        [provider("groq")],
        rate_limit_wait_seconds=20,
        client_factory=fake,
        sleep=sleeps.append,
    ).complete(USER)

    assert sleeps == [pytest.approx(7.7)]


def test_the_shortest_wait_of_the_chain_is_used() -> None:
    fake = FakeProviders(
        {
            "groq": [rate_limited({"retry-after": "9"}), completion()],
            "gemini": [rate_limited({"retry-after": "3"}), completion()],
        }
    )
    sleeps: list[float] = []
    client = LLMClient(
        [provider("groq"), provider("gemini")],
        rate_limit_wait_seconds=20, client_factory=fake, sleep=sleeps.append,
    )  # fmt: skip

    assert client.complete(USER).provider == "groq"
    assert sleeps == [3.5]


@pytest.mark.parametrize(
    ("headers", "wait_limit"),
    [({"retry-after": "45"}, 20), ({"retry-after": "2"}, 0), ({}, 20)],
    ids=["too long", "waiting off", "no hint"],
)
def test_no_wait_when_too_long_disabled_or_unknown(headers, wait_limit) -> None:
    fake = FakeProviders({"groq": [rate_limited(headers), completion()]})
    sleeps: list[float] = []
    client = LLMClient(
        [provider("groq")], rate_limit_wait_seconds=wait_limit, client_factory=fake,
        sleep=sleeps.append,
    )  # fmt: skip

    with pytest.raises(LLMUnavailableError):
        client.complete(USER)
    assert sleeps == [] and fake.calls() == ["groq"]


def test_the_chain_is_retried_only_once() -> None:
    fake = FakeProviders(
        {
            "groq": [
                rate_limited({"retry-after": "1"}),
                rate_limited({"retry-after": "1"}),
            ]
        }
    )
    sleeps: list[float] = []
    client = LLMClient(
        [provider("groq")],
        rate_limit_wait_seconds=20,
        client_factory=fake,
        sleep=sleeps.append,
    )

    with pytest.raises(LLMUnavailableError):
        client.complete(USER)
    assert sleeps == [1.5] and fake.calls() == ["groq", "groq"]


def test_a_working_fallback_means_no_wait() -> None:
    fake = FakeProviders(
        {"groq": [rate_limited({"retry-after": "1"})], "gemini": [completion()]}
    )
    sleeps: list[float] = []
    client = LLMClient(
        [provider("groq"), provider("gemini")],
        rate_limit_wait_seconds=20, client_factory=fake, sleep=sleeps.append,
    )  # fmt: skip

    assert client.complete(USER).provider == "gemini"
    assert sleeps == []


# --- stream_turn: rounds that may call tools (F4.1) ---

from openai.types.chat import ChatCompletionChunk as _Chunk  # noqa: E402

from app.llm.client import PROVIDER_KEY, prepare_messages  # noqa: E402


def tool_chunk(index: int, *, id=None, name=None, args=None, extra=None) -> _Chunk:
    call: dict = {"index": index, "type": "function", "function": {}}
    if id:
        call["id"] = id
    if name:
        call["function"]["name"] = name
    if args is not None:
        call["function"]["arguments"] = args
    if extra:
        call.update(extra)
    return _Chunk.model_validate(
        {"id": "k", "object": "chat.completion.chunk", "created": 0, "model": "m",
         "choices": [{"index": 0, "delta": {"tool_calls": [call]}, "finish_reason": None}]}
    )  # fmt: skip


def usage_chunk(prompt: int, completion: int, finish: str | None = None) -> _Chunk:
    choices = [{"index": 0, "delta": {}, "finish_reason": finish}] if finish else []
    return _Chunk.model_validate(
        {"id": "k", "object": "chat.completion.chunk", "created": 0, "model": "m",
         "choices": choices,
         "usage": {"prompt_tokens": prompt, "completion_tokens": completion,
                   "total_tokens": prompt + completion}}
    )  # fmt: skip


def test_streamed_tool_calls_are_assembled_from_fragments() -> None:
    raw = FakeStream([
        tool_chunk(0, id="call_a", name="search_f1_knowledge", args='{"que'),
        tool_chunk(0, args='ry": "Suzuka 1989"}',
                   extra={"extra_content": {"google": {"thought_signature": "sig"}}}),
        usage_chunk(120, 30, finish="tool_calls"),
    ])  # fmt: skip
    client, fake, _ = make({"groq": [raw]})

    turn = client.stream_turn(USER, tools=TOOLS, max_tokens=500)

    (call,) = turn.tool_calls
    assert (call.id, call.name, call.arguments) == (
        "call_a",
        "search_f1_knowledge",
        {"query": "Suzuka 1989"},
    )
    assert call.extra == {"extra_content": {"google": {"thought_signature": "sig"}}}
    assert list(turn) == []  # nothing to stream
    assert (turn.usage.prompt_tokens, turn.usage.completion_tokens) == (120, 30)
    assert turn.finish_reason == "tool_calls" and raw.closed
    _, request = fake.requests[0]
    assert request["stream"] is True and request["stream_options"] == {
        "include_usage": True
    }
    assert request["tools"] == TOOLS


def test_a_bad_streamed_tool_call_falls_back() -> None:
    bad = FakeStream([tool_chunk(0, id="c", name="drop_tables", args="{}")])
    good = FakeStream([tool_chunk(0, id="c", name="search_f1_knowledge", args="{}")])
    client, fake, _ = make({"groq": [bad], "gemini": [good]})

    turn = client.stream_turn(USER, tools=TOOLS)

    assert turn.provider == "gemini" and turn.tool_calls[0].arguments == {}
    assert fake.calls() == ["groq", "gemini"]


def test_a_text_turn_streams_and_records_usage_after_iteration() -> None:
    raw = FakeStream(
        [chunk("James "), chunk("Hunt."), usage_chunk(80, 4, finish="stop")]
    )
    client, _, _ = make({"groq": [raw]})

    turn = client.stream_turn(USER, tools=TOOLS)

    assert turn.tool_calls == () and turn.usage is None  # not yet
    assert list(turn) == ["James ", "Hunt."]
    assert turn.content == "James Hunt." and turn.finish_reason == "stop"
    assert turn.usage.prompt_tokens == 80 and raw.closed


def test_tool_calls_after_text_are_kept_if_usable() -> None:
    raw = FakeStream([
        chunk("Let me check. "),
        tool_chunk(0, id="c1", name="search_f1_knowledge", args='{"query": "x"}'),
    ])  # fmt: skip
    client, _, _ = make({"groq": [raw]})

    turn = client.stream_turn(USER, tools=TOOLS)
    assert list(turn) == ["Let me check. "]
    assert [c.name for c in turn.tool_calls] == ["search_f1_knowledge"]


def test_unusable_tool_calls_after_text_are_dropped(caplog) -> None:
    raw = FakeStream([chunk("Answer."), tool_chunk(0, id="c1", name="nope", args="{}")])
    client, _, _ = make({"groq": [raw]})

    turn = client.stream_turn(USER, tools=TOOLS)
    assert list(turn) == ["Answer."] and turn.tool_calls == ()
    assert "Dropped unusable tool calls" in caplog.text


def test_tool_extras_are_kept_by_complete_too() -> None:
    call = tool_call() | {"extra_content": {"google": {"thought_signature": "s"}}}
    client, _, _ = make({"groq": [completion(content=None, tool_calls=[call])]})

    (parsed,) = client.complete(USER, tools=TOOLS).tool_calls

    assert parsed.extra == {"extra_content": {"google": {"thought_signature": "s"}}}


# --- tool history across providers ---

HISTORY = USER + [
    {"role": "assistant", "content": None, PROVIDER_KEY: "groq",
     "tool_calls": [{"id": "call_1", "type": "function",
                     "function": {"name": "search_f1_knowledge", "arguments": '{"query": "1976"}'},
                     "extra_content": {"google": {"thought_signature": "sig"}}}]},
    {"role": "tool", "tool_call_id": "call_1", "content": '{"results": []}'},
]  # fmt: skip


def test_the_same_provider_gets_the_tool_history_unchanged() -> None:
    prepared = prepare_messages(HISTORY, "groq")

    assert prepared[1]["tool_calls"] == HISTORY[1]["tool_calls"]  # extras kept
    assert PROVIDER_KEY not in prepared[1]
    assert prepared[2] == HISTORY[2]


def test_another_provider_gets_the_tool_history_as_text() -> None:
    prepared = prepare_messages(HISTORY, "gemini")

    assert prepared[0] == USER[0]
    assert prepared[1] == {
        "role": "assistant",
        "content": 'I called search_f1_knowledge with {"query": "1976"}.',
    }
    assert prepared[2]["role"] == "user"
    assert prepared[2]["content"].startswith(
        "Result of search_f1_knowledge (tool output: data"
    )
    assert prepared[2]["content"].endswith('{"results": []}')


def test_history_without_an_owner_is_sent_as_is() -> None:
    history = [dict(m) for m in HISTORY]
    del history[1][PROVIDER_KEY]

    assert (
        prepare_messages(history, "gemini")[1]["tool_calls"] == HISTORY[1]["tool_calls"]
    )


def test_complete_and_stream_turn_send_prepared_messages() -> None:
    client, fake, _ = make(
        {"groq": [status_error(openai.RateLimitError, 429)] * 2,
         "gemini": [FakeStream([chunk("ok")]), completion()]}
    )  # fmt: skip

    list(client.stream_turn(HISTORY))
    client.complete(HISTORY)

    for name, request in fake.requests:
        if name == "gemini":
            assert all("tool_calls" not in m for m in request["messages"])
