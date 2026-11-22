"""LLM access with free-provider fallback (Phase 3).

    from app.llm import build_llm_client
    llm = build_llm_client(settings)
    answer = llm.complete([{"role": "user", "content": "Who won in 1976?"}])

Try the configured providers: `uv run python -m app.llm "question"`.
"""

from app.core.config import Settings
from app.llm.client import LLMClient, LLMResponse, LLMStream, ToolCall, Usage
from app.llm.errors import LLMError, LLMStreamInterruptedError, LLMUnavailableError
from app.llm.providers import Provider, providers_from_settings


def build_llm_client(settings: Settings, *, only: str | None = None) -> LLMClient:
    """The configured providers in fallback order; `only` keeps just that one."""
    providers = providers_from_settings(settings)
    if only is not None:
        providers = [p for p in providers if p.name == only]
    return LLMClient(
        providers,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )


__all__ = [
    "LLMClient",
    "LLMError",
    "LLMResponse",
    "LLMStream",
    "LLMStreamInterruptedError",
    "LLMUnavailableError",
    "Provider",
    "ToolCall",
    "Usage",
    "build_llm_client",
    "providers_from_settings",
]
