"""What every LLM tool looks like to the orchestrator (F3.7).

A tool has a `name`, an OpenAI-format `definition()` to offer the model, and
`call(arguments)`, which takes the model's (untrusted) arguments and always
returns a ToolOutcome: the JSON payload for the tool message, whether it
worked, and any sources the answer may cite. Expected failures (bad
arguments, a rejected query, a database or model problem) become an error
payload the model can read; they are never raised.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class Source:
    """Something the answer can cite, e.g. a Wikipedia chunk."""

    id: str  # "S1", "S2": unique within one answer
    title: str
    url: str
    section: str | None = None
    season: int | None = None


@dataclass(frozen=True)
class ToolOutcome:
    name: str
    payload: dict[str, Any]
    ok: bool
    sources: tuple[Source, ...] = field(default=())

    @classmethod
    def error(cls, name: str, message: str) -> "ToolOutcome":
        return cls(name, {"error": message}, ok=False)


class Tool(Protocol):
    name: str

    def definition(self) -> dict[str, Any]:
        """The OpenAI-format tool definition offered to the model."""
        ...

    def call(self, arguments: dict[str, Any], **context: Any) -> ToolOutcome:
        """Run with the model's arguments; never raises for expected failures."""
        ...
