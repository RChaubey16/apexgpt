"""LLM client with free-provider fallback (F3.3).

Talks to Groq, Gemini and OpenRouter through their OpenAI-compatible APIs with
the official openai SDK (chosen over LiteLLM, which added ~213 MB of RAM and
3 s of import time; see the Decision Log in docs/PROGRESS.md).

For each request the configured providers are tried in order:
- a timeout, connection error or 5xx is retried on the same provider
  (`max_retries` times, short backoff), then the next provider is tried;
- any other API error (429 rate limit, 401/403 bad key, 404 retired model,
  400 e.g. Groq's `tool_use_failed`) moves straight to the next provider;
- a response we can't use (no content and no tool calls, a tool we didn't
  offer, arguments that aren't a JSON object) also moves to the next provider.
When every provider fails, LLMUnavailableError is raised with a safe message.

Streaming falls back the same way until the first token arrives; after that
the answer is already being shown, so a failure raises
LLMStreamInterruptedError instead of starting again elsewhere.

Logs carry the provider, model, attempt, error class and status code only,
never prompts, answers or keys.
"""

import json
import logging
import re
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

import openai

from app.llm.errors import LLMStreamInterruptedError, LLMUnavailableError
from app.llm.providers import Provider

logger = logging.getLogger(__name__)

# OpenAI chat format, as plain dicts: what every provider accepts.
Message = dict[str, Any]
Tool = dict[str, Any]

ROLES = {"system", "user", "assistant", "tool"}
TOOL_CHOICES = {"auto", "none", "required"}
MAX_TOKENS_LIMIT = 8192
# Generous for prompt + retrieved chunks; protects the free-tier quotas.
MAX_PROMPT_CHARS = 100_000
BACKOFF_SECONDS = (0.5, 1.0, 2.0)
_TOOL_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

T = TypeVar("T")


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True)
class LLMResponse:
    content: str | None
    tool_calls: tuple[ToolCall, ...]
    finish_reason: str | None
    provider: str
    model: str
    usage: Usage | None
    latency_ms: int


class InvalidResponseError(Exception):
    """A provider answered, but with something we can't use (internal)."""


class LLMStream:
    """A streamed answer: iterate for text pieces. Single use.

    `provider` and `model` name who is answering (known before the first piece).
    """

    def __init__(self, provider: str, model: str, pieces: Iterator[str]) -> None:
        self.provider = provider
        self.model = model
        self._pieces = pieces

    def __iter__(self) -> Iterator[str]:
        return self._pieces


def _is_transient(exc: openai.APIError) -> bool:
    """Worth retrying on the same provider: timeouts, connection errors, 5xx."""
    if isinstance(exc, openai.APIConnectionError):  # includes APITimeoutError
        return True
    return isinstance(exc, openai.APIStatusError) and exc.status_code >= 500


def _status(exc: BaseException) -> int | None:
    return exc.status_code if isinstance(exc, openai.APIStatusError) else None


def validate_request(
    messages: Sequence[Message],
    tools: Sequence[Tool] | None,
    tool_choice: str | None,
    temperature: float,
    max_tokens: int,
) -> set[str]:
    """Check what we send (a programming error raises ValueError); returns tool names."""
    if not messages:
        raise ValueError("at least one message is required")
    total = 0
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in ROLES:
            raise ValueError(f"each message needs a role in {sorted(ROLES)}")
        content = message.get("content")
        if content is None:
            if not (message["role"] == "assistant" and message.get("tool_calls")):
                raise ValueError(
                    "only an assistant message with tool_calls may omit content"
                )
        elif not isinstance(content, str):
            raise ValueError("message content must be a string")
        else:
            total += len(content)
        if message["role"] == "tool" and not message.get("tool_call_id"):
            raise ValueError("a tool message needs its tool_call_id")
    if total > MAX_PROMPT_CHARS:
        raise ValueError(f"the prompt is longer than {MAX_PROMPT_CHARS} characters")

    names: set[str] = set()
    for tool in tools or []:
        function = tool.get("function") if isinstance(tool, dict) else None
        if tool.get("type") != "function" or not isinstance(function, dict):
            raise ValueError("tools must be {'type': 'function', 'function': {...}}")
        name = function.get("name")
        if not isinstance(name, str) or not _TOOL_NAME.match(name):
            raise ValueError("tool names must be 1-64 letters, digits, _ or -")
        if name in names:
            raise ValueError(f"duplicate tool name {name!r}")
        if not isinstance(function.get("parameters", {}), dict):
            raise ValueError(f"tool {name!r} parameters must be a JSON schema object")
        names.add(name)
    if tool_choice is not None:
        if not tools:
            raise ValueError("tool_choice needs tools")
        if tool_choice not in TOOL_CHOICES:
            raise ValueError(f"tool_choice must be one of {sorted(TOOL_CHOICES)}")
    if not 0 <= temperature <= 2:
        raise ValueError("temperature must be between 0 and 2")
    if not 1 <= max_tokens <= MAX_TOKENS_LIMIT:
        raise ValueError(f"max_tokens must be between 1 and {MAX_TOKENS_LIMIT}")
    return names


def parse_response(
    raw: Any, provider: Provider, tool_names: set[str], latency_ms: int
) -> LLMResponse:
    """Validate a chat completion; InvalidResponseError if it can't be used."""
    choices = getattr(raw, "choices", None)
    if not choices:
        raise InvalidResponseError("no choices")
    choice = choices[0]
    message = getattr(choice, "message", None)
    if message is None:
        raise InvalidResponseError("no message")
    content = message.content if isinstance(message.content, str) else None

    calls: list[ToolCall] = []
    for index, call in enumerate(message.tool_calls or []):
        function = getattr(call, "function", None)
        if function is None:
            raise InvalidResponseError("unsupported tool call type")
        if function.name not in tool_names:
            raise InvalidResponseError("call to a tool that was not offered")
        try:
            arguments = json.loads(function.arguments or "{}")
        except (TypeError, ValueError):
            raise InvalidResponseError("tool arguments are not valid JSON") from None
        if not isinstance(arguments, dict):
            raise InvalidResponseError("tool arguments are not a JSON object")
        calls.append(ToolCall(call.id or f"call_{index}", function.name, arguments))

    if not (content and content.strip()) and not calls:
        raise InvalidResponseError("empty answer")
    usage = getattr(raw, "usage", None)
    return LLMResponse(
        content=content,
        tool_calls=tuple(calls),
        finish_reason=getattr(choice, "finish_reason", None),
        provider=provider.name,
        model=provider.model,
        usage=(
            Usage(usage.prompt_tokens or 0, usage.completion_tokens or 0)
            if usage
            else None
        ),
        latency_ms=latency_ms,
    )


def _chunk_text(chunk: Any) -> str:
    choices = getattr(chunk, "choices", None)
    if not choices:
        return ""
    delta = getattr(choices[0], "delta", None)
    text = getattr(delta, "content", None)
    return text if isinstance(text, str) else ""


class LLMClient:
    def __init__(
        self,
        providers: Sequence[Provider],
        *,
        timeout: float = 30.0,
        max_retries: int = 1,
        client_factory: Callable[..., Any] = openai.OpenAI,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._providers = list(providers)
        self._timeout = timeout
        self._max_retries = max_retries
        self._client_factory = client_factory
        self._sleep = sleep
        self._clients: dict[str, Any] = {}

    @property
    def provider_names(self) -> list[str]:
        return [p.name for p in self._providers]

    def _client(self, provider: Provider) -> Any:
        if provider.name not in self._clients:
            self._clients[provider.name] = self._client_factory(
                api_key=provider.api_key.get_secret_value(),
                base_url=provider.base_url,
                timeout=self._timeout,
                max_retries=0,  # retries and fallback are ours
            )
        return self._clients[provider.name]

    def _with_fallback(self, attempt_fn: Callable[[Provider], T]) -> T:
        if not self._providers:
            raise LLMUnavailableError(
                "No language model is configured (set GROQ_API_KEY, GEMINI_API_KEY "
                "or OPENROUTER_API_KEY)"
            )
        for provider in self._providers:
            for attempt in range(1, self._max_retries + 2):
                try:
                    return attempt_fn(provider)
                except openai.APIError as exc:
                    transient = _is_transient(exc)
                    logger.warning(
                        "LLM call failed: provider=%s model=%s attempt=%d error=%s status=%s",
                        provider.name,
                        provider.model,
                        attempt,
                        type(exc).__name__,
                        _status(exc),
                    )
                    if transient and attempt <= self._max_retries:
                        self._sleep(
                            BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS)) - 1]
                        )
                        continue
                    break
                except InvalidResponseError as exc:
                    logger.warning(
                        "LLM response unusable: provider=%s model=%s reason=%s",
                        provider.name,
                        provider.model,
                        exc,
                    )
                    break
        raise LLMUnavailableError("The language model is unavailable right now")

    def complete(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[Tool] | None = None,
        tool_choice: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """One answer (text and/or tool calls) from the first provider that works."""
        tool_names = validate_request(
            messages, tools, tool_choice, temperature, max_tokens
        )
        request: dict[str, Any] = {
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            request["tools"] = list(tools)
            if tool_choice:
                request["tool_choice"] = tool_choice

        def attempt(provider: Provider) -> LLMResponse:
            started = time.perf_counter()
            raw = self._client(provider).chat.completions.create(
                model=provider.model, **request
            )
            latency = round((time.perf_counter() - started) * 1000)
            response = parse_response(raw, provider, tool_names, latency)
            logger.info(
                "LLM answered: provider=%s model=%s latency_ms=%d tool_calls=%d",
                provider.name,
                provider.model,
                latency,
                len(response.tool_calls),
            )
            return response

        return self._with_fallback(attempt)

    def stream(
        self,
        messages: Sequence[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> LLMStream:
        """A streamed text answer. Falls back between providers until the first
        token; a failure after it raises LLMStreamInterruptedError while iterating."""
        validate_request(messages, None, None, temperature, max_tokens)

        def attempt(provider: Provider) -> LLMStream:
            raw = self._client(provider).chat.completions.create(
                model=provider.model,
                messages=list(messages),
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            chunks = iter(raw)
            try:
                first = ""
                for chunk in chunks:  # errors here still fall back
                    first = _chunk_text(chunk)
                    if first:
                        break
                if not first:
                    raise InvalidResponseError("empty stream")
            except BaseException:
                _close(raw)
                raise
            return LLMStream(
                provider.name, provider.model, self._rest(provider, raw, chunks, first)
            )

        return self._with_fallback(attempt)

    @staticmethod
    def _rest(
        provider: Provider, raw: Any, chunks: Iterator[Any], first: str
    ) -> Iterator[str]:
        try:
            yield first
            for chunk in chunks:
                text = _chunk_text(chunk)
                if text:
                    yield text
        except openai.APIError as exc:
            logger.warning(
                "LLM stream interrupted: provider=%s model=%s error=%s status=%s",
                provider.name,
                provider.model,
                type(exc).__name__,
                _status(exc),
            )
            raise LLMStreamInterruptedError(
                "The answer was interrupted; please try again"
            ) from None
        finally:
            _close(raw)


def _close(raw: Any) -> None:
    close = getattr(raw, "close", None)
    if callable(close):
        close()
