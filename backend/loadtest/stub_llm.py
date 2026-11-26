"""A stand-in LLM for load tests (F6.4): an OpenAI-compatible chat API.

The backend talks to it through LLM_GROQ_BASE_URL, so a load test exercises
everything real (entity resolution, hybrid search and reranking on one CPU, the
stats database, SSE) without spending free-tier quota. It answers like the
real pipeline's model does:

1. a streamed round with tools offered and no tool result yet → one tool call:
   ``query_stats`` for "how many / most" questions, else ``search_f1_knowledge``
   with the question as the search terms;
2. a round after a tool result → a streamed answer citing [S1];
3. a request without streaming (the follow-up condenser) → the question back.

Delays imitate a fast free-tier model (environment, milliseconds):
STUB_TOOL_DELAY_MS (600), STUB_FIRST_TOKEN_MS (400), STUB_TOKEN_MS (15) and
STUB_TOKENS (40 pieces per answer).

    uv run uvicorn loadtest.stub_llm:app --host 0.0.0.0 --port 9100
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

STATS_TOOL = "query_stats"
KNOWLEDGE_TOOL = "search_f1_knowledge"
STATS_SQL = "SELECT driver_name, wins FROM v_driver_career ORDER BY wins DESC LIMIT 5"
# How app.llm.client.prepare_messages hands another provider's tool result on.
FLATTENED_RESULT = "Result of "
STATS_QUESTION = re.compile(r"\b(how many|most|record|points)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Delays:
    tool_ms: int = 600
    first_token_ms: int = 400
    token_ms: int = 15
    tokens: int = 40

    @classmethod
    def from_env(cls) -> Delays:
        def number(name: str, default: int) -> int:
            raw = os.environ.get(name, "")
            if not raw.strip():
                return default
            value = int(raw)
            if not 0 <= value <= 60_000:
                raise ValueError(f"{name} must be between 0 and 60000")
            return value

        return cls(
            tool_ms=number("STUB_TOOL_DELAY_MS", cls.tool_ms),
            first_token_ms=number("STUB_FIRST_TOKEN_MS", cls.first_token_ms),
            token_ms=number("STUB_TOKEN_MS", cls.token_ms),
            tokens=number("STUB_TOKENS", cls.tokens),
        )


def question_of(messages: list[dict[str, Any]]) -> str:
    """The question: the first paragraph of the last user message (the
    orchestrator appends entity hints after a blank line)."""
    for message in reversed(messages):
        if message.get("role") == "user" and isinstance(message.get("content"), str):
            text = message["content"]
            if text.startswith(FLATTENED_RESULT):
                continue  # a tool result from another provider's round
            # The condenser sends "<conversation>…</conversation>\n\nLast message: q".
            if "Last message:" in text:
                return text.rsplit("Last message:", 1)[1].strip()
            return text.split("\n\n", 1)[0].strip()
    return ""


def plan(body: dict[str, Any]) -> tuple[str, Any]:
    """("tool", (name, arguments)) | ("text", answer) | ("complete", text)."""
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise HTTPException(400, "messages must be a non-empty list")
    question = question_of(messages)
    if not body.get("stream"):
        return "complete", question
    offered = {
        t.get("function", {}).get("name")
        for t in body.get("tools") or []
        if isinstance(t, dict)
    }
    answered = any(m.get("role") == "tool" for m in messages) or any(
        m.get("role") == "user"
        and str(m.get("content", "")).startswith(FLATTENED_RESULT)
        for m in messages
    )
    if offered and not answered:
        if STATS_TOOL in offered and STATS_QUESTION.search(question):
            return "tool", (STATS_TOOL, {"sql": STATS_SQL})
        if KNOWLEDGE_TOOL in offered:
            return "tool", (KNOWLEDGE_TOOL, {"query": question[:300] or "Formula 1"})
    cite = "[S1]" if answered else ""
    return "text", f"Stub answer to: {question} {cite}".strip()


def _chunk(model: str, delta: dict[str, Any], finish: str | None = None) -> str:
    data = {
        "id": "stub",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(data)}\n\n"


def _usage(model: str, completion: int) -> str:
    data = {
        "id": "stub",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [],
        "usage": {
            "prompt_tokens": 3000,
            "completion_tokens": completion,
            "total_tokens": 3000 + completion,
        },
    }
    return f"data: {json.dumps(data)}\n\n"


def split(text: str, pieces: int) -> list[str]:
    """``text`` in about ``pieces`` parts that join back to it exactly."""
    if pieces <= 1 or len(text) <= 1:
        return [text]
    size = max(1, -(-len(text) // pieces))
    return [text[i : i + size] for i in range(0, len(text), size)]


async def _stream(
    kind: str, payload: Any, model: str, delays: Delays
) -> AsyncIterator[str]:
    yield _chunk(model, {"role": "assistant", "content": ""})
    if kind == "tool":
        await asyncio.sleep(delays.tool_ms / 1000)
        name, arguments = payload
        yield _chunk(
            model,
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_stub",
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(arguments)},
                    }
                ]
            },
        )
        yield _chunk(model, {}, "tool_calls")
        yield _usage(model, 40)
    else:
        await asyncio.sleep(delays.first_token_ms / 1000)
        parts = split(payload, delays.tokens)
        for index, part in enumerate(parts):
            if index:
                await asyncio.sleep(delays.token_ms / 1000)
            yield _chunk(model, {"content": part})
        yield _chunk(model, {}, "stop")
        yield _usage(model, len(parts))
    yield "data: [DONE]\n\n"


def create_app(delays: Delays | None = None) -> FastAPI:
    app = FastAPI(title="ApexGPT stub LLM")
    app.state.delays = delays or Delays.from_env()
    app.state.requests = 0

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "requests": app.state.requests}

    @app.post("/v1/chat/completions", response_model=None)
    async def completions(request: Request) -> StreamingResponse | JSONResponse:
        try:
            body = await request.json()
        except ValueError:
            raise HTTPException(400, "body must be JSON") from None
        if not isinstance(body, dict):
            raise HTTPException(400, "body must be a JSON object")
        app.state.requests += 1
        kind, payload = plan(body)
        model = str(body.get("model") or "stub")
        if kind == "complete":
            await asyncio.sleep(app.state.delays.first_token_ms / 1000)
            return JSONResponse(
                {
                    "id": "stub",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": payload},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 400,
                        "completion_tokens": 20,
                        "total_tokens": 420,
                    },
                }
            )
        return StreamingResponse(
            _stream(kind, payload, model, app.state.delays),
            media_type="text/event-stream",
        )

    return app


app = create_app()
