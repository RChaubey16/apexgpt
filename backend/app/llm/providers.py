"""The free-tier LLM providers, tried in order: Groq → Gemini → OpenRouter.

All three expose OpenAI-compatible chat completion APIs, so one client (the
official openai SDK) talks to each through its base URL. A provider is used only
when its API key is set; the order is fixed (docs/MVP-PLAN.md).

Free-tier model lists change, so each model is a setting. Defaults:
- Groq: openai/gpt-oss-120b. The plan's Llama 3.3 70B is no longer offered;
  gpt-oss-120b made correct tool calls in ~0.6 s when F3.3 was built.
- Gemini, OpenRouter: not verified when F3.3 was built (no keys). A wrong or
  retired model fails with 404 and the client falls through to the next one.
"""

from dataclasses import dataclass, field

from pydantic import SecretStr

from app.core.config import Settings

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    model: str
    # repr=False: a Provider can end up in logs or tracebacks.
    api_key: SecretStr = field(repr=False)


def providers_from_settings(settings: Settings) -> list[Provider]:
    """The configured providers, in fallback order. Empty if no key is set."""
    candidates = [
        ("groq", GROQ_BASE_URL, settings.llm_groq_model, settings.groq_api_key),
        ("gemini", GEMINI_BASE_URL, settings.llm_gemini_model, settings.gemini_api_key),
        (
            "openrouter",
            OPENROUTER_BASE_URL,
            settings.llm_openrouter_model,
            settings.openrouter_api_key,
        ),
    ]
    return [
        Provider(name, base_url, model, key)
        for name, base_url, model, key in candidates
        if key is not None
    ]
