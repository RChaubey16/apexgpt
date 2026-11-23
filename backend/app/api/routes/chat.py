"""`POST /api/chat`: a grounded, cited answer streamed as Server-Sent Events (F4.1).

Request: `{"question": "...", "history": [{"role": "user"|"assistant",
"content": "..."}, ...]}`. The question is 1-500 characters; `history` (F4.2,
optional) is the recent conversation, oldest first, up to 20 messages of up to
8,000 characters, and is used only to turn a follow-up into a standalone
question. Unknown fields are rejected, so a client can't send something it
thinks is used. A bad body is a normal 422 before anything streams.

Response: `text/event-stream`. Each event is `event: <type>` plus one JSON
`data:` line:

| event    | data                                                        | when |
|----------|-------------------------------------------------------------|------|
| question | {"text"}                                                     | a follow-up was rewritten; the question answered |
| tool    | {"name", "status": "started"/"finished", "ok"}               | a tool runs (so the UI can say "Searching…") |
| table    | {"columns": [...], "rows": [[...]], "note"?}                 | a stats query returned rows |
| token    | {"text"}                                                     | the next piece of the answer (markdown) |
| citation | {"id", "title", "url", "section", "season"}                 | a source is cited for the first time |
| done     | {"question", "provider", "model", "sources": [ids], "tools", | the answer is complete |
|          |  "latency_ms", "prompt_tokens", "completion_tokens"}         | |
| error    | {"message"}                                                  | no answer (safe to show); the stream ends |

The plan lists token/citation/table/done/error; `tool` is added because the
tool rounds take 1-4 s with nothing else to show, and `question` so the UI can
show how a follow-up was understood.
"""

import json
import logging
from collections.abc import Iterator, Sequence
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.answer.followups import (
    MAX_HISTORY_CHARS,
    MAX_HISTORY_MESSAGES,
    HistoryMessage,
)
from app.answer.orchestrator import (
    AnswerUnavailableError,
    CitationEvent,
    DoneEvent,
    Orchestrator,
    QuestionEvent,
    TableEvent,
    TokenEvent,
    ToolEvent,
)
from app.retrieval.search import MAX_QUERY_CHARS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    # Stop proxies (nginx, Traefik/Coolify) from buffering the stream.
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}
GENERIC_ERROR = "Something went wrong while answering; please try again"


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_HISTORY_CHARS)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    history: list[ChatMessage] = Field(
        default_factory=list, max_length=MAX_HISTORY_MESSAGES
    )

    def history_messages(self) -> list[HistoryMessage]:
        return [HistoryMessage(m.role, m.content) for m in self.history]


def get_orchestrator(request: Request) -> Orchestrator:
    return request.app.state.orchestrator


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def event_frames(
    orchestrator: Orchestrator,
    question: str,
    history: Sequence[HistoryMessage] = (),
) -> Iterator[str]:
    """SSE frames for one question; always ends with `done` or `error`."""
    try:
        for event in orchestrator.stream(question, history):
            if isinstance(event, TokenEvent):
                yield sse("token", {"text": event.text})
            elif isinstance(event, CitationEvent):
                s = event.source
                yield sse(
                    "citation",
                    {"id": s.id, "title": s.title, "url": s.url,
                     "section": s.section, "season": s.season},
                )  # fmt: skip
            elif isinstance(event, TableEvent):
                data: dict[str, Any] = {
                    "columns": list(event.columns),
                    "rows": [list(r) for r in event.rows],
                }
                if event.note:
                    data["note"] = event.note
                yield sse("table", data)
            elif isinstance(event, ToolEvent):
                data = {"name": event.name, "status": event.status}
                if event.ok is not None:
                    data["ok"] = event.ok
                yield sse("tool", data)
            elif isinstance(event, QuestionEvent):
                yield sse("question", {"text": event.text})
            elif isinstance(event, DoneEvent):
                a = event.answer
                yield sse(
                    "done",
                    {
                        "question": a.question,
                        "provider": a.provider,
                        "model": a.model,
                        "sources": [s.id for s in a.sources],
                        "tools": [{"name": c.name, "ok": c.ok} for c in a.tool_calls],
                        "latency_ms": a.latency_ms,
                        "prompt_tokens": a.prompt_tokens,
                        "completion_tokens": a.completion_tokens,
                    },
                )
    except AnswerUnavailableError as exc:
        yield sse("error", {"message": str(exc)})
    except (
        ValueError
    ) as exc:  # the question failed normalisation (e.g. only control chars)
        yield sse("error", {"message": str(exc)})
    except Exception:  # never a traceback in the stream
        logger.exception("Chat stream failed")
        yield sse("error", {"message": GENERIC_ERROR})


@router.post(
    "/chat",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
def chat(
    body: ChatRequest,
    orchestrator: Annotated[Orchestrator, Depends(get_orchestrator)],
) -> StreamingResponse:
    # A sync generator: Starlette iterates it in a worker thread, and closes it
    # (ending the LLM stream) if the client disconnects.
    return StreamingResponse(
        event_frames(orchestrator, body.question, body.history_messages()),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
