"""The free-tier LLM providers, tried in order: Groq → Gemini → OpenRouter.

All three expose OpenAI-compatible chat completion APIs, so one client (the
official openai SDK) talks to each through its base URL. A provider is used only
when its API key is set; the order is fixed (docs/archive/v1.0.0-mvp/MVP-PLAN.md).

Free-tier model lists change, so each model is a setting. Defaults, each
chosen after a live tool-call test:
- Groq: openai/gpt-oss-120b (F3.3; the plan's Llama 3.3 70B is no longer
  offered). Correct tool calls in ~0.6 s.
- Gemini: gemini-3.1-flash-lite (F3.7). gemini-2.5-flash is closed to new
  users; the newer flash models (3.5-3.8) were overloaded when tested (503s,
  timeouts, 19-34 s answers), and a fallback must be quick. ~2 s.
- OpenRouter: nvidia/nemotron-3-ultra-550b-a55b:free (F3.7); the earlier
  gpt-oss-120b:free is no longer offered. ~1.3 s.
A wrong or retired model fails with 404 and the client falls through.
"""

from dataclasses import dataclass, field

from pydantic import SecretStr

from app.core.config import Settings

# The defaults; each is a setting (LLM_GROQ_BASE_URL, …) so the load test can
# point the backend at a stub LLM (F6.4).
GROQ_BASE_URL = Settings.model_fields["llm_groq_base_url"].default
GEMINI_BASE_URL = Settings.model_fields["llm_gemini_base_url"].default
OPENROUTER_BASE_URL = Settings.model_fields["llm_openrouter_base_url"].default


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
        (
            "groq",
            settings.llm_groq_base_url,
            settings.llm_groq_model,
            settings.groq_api_key,
        ),
        (
            "gemini",
            settings.llm_gemini_base_url,
            settings.llm_gemini_model,
            settings.gemini_api_key,
        ),
        (
            "openrouter",
            settings.llm_openrouter_base_url,
            settings.llm_openrouter_model,
            settings.openrouter_api_key,
        ),
    ]
    return [
        Provider(name, base_url, model, key)
        for name, base_url, model, key in candidates
        if key is not None
    ]
