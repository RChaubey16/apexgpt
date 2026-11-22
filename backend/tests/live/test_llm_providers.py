"""The real LLM providers: each configured one answers, calls tools and streams.

Opt-in (CI has no keys, and this spends free-tier quota):

    LLM_LIVE_TESTS=1 uv run pytest -m llm

Uses the keys from .env; providers without a key are skipped. Each provider is
tested alone (no fallback), so a broken one fails instead of being hidden.
"""

import os

import pytest

from app.core.config import Settings
from app.llm import build_llm_client, providers_from_settings

pytestmark = pytest.mark.llm

if os.environ.get("LLM_LIVE_TESTS") != "1":
    pytest.skip("LLM_LIVE_TESTS=1 not set", allow_module_level=True)

SETTINGS = Settings()
CONFIGURED = [p.name for p in providers_from_settings(SETTINGS)]
ALL = ["groq", "gemini", "openrouter"]

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_f1_knowledge",
            "description": "Search Formula 1 history articles.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }
]


def client_for(name: str):
    if name not in CONFIGURED:
        pytest.skip(f"no API key for {name}")
    return build_llm_client(SETTINGS, only=name)


@pytest.mark.parametrize("name", ALL)
def test_answers_a_question(name: str) -> None:
    response = client_for(name).complete(
        [
            {
                "role": "user",
                "content": "Who won the 1976 Formula One drivers' title? Answer with the name only.",
            }
        ],
        max_tokens=300,
    )

    assert response.provider == name
    assert "Hunt" in (response.content or "")


@pytest.mark.parametrize("name", ALL)
def test_calls_a_tool(name: str) -> None:
    response = client_for(name).complete(
        [{"role": "user", "content": "What happened at Suzuka in 1989? Use the tool."}],
        tools=TOOLS,
        tool_choice="required",
        max_tokens=300,
    )

    call, *_ = response.tool_calls
    assert call.name == "search_f1_knowledge"
    assert isinstance(call.arguments.get("query"), str) and call.arguments["query"]


@pytest.mark.parametrize("name", ALL)
def test_streams(name: str) -> None:
    stream = client_for(name).stream(
        [
            {
                "role": "user",
                "content": "Name the circuit at Monza in five words or fewer.",
            }
        ],
        max_tokens=300,
    )

    text = "".join(stream)
    assert stream.provider == name
    assert "Monza" in text or "Nazionale" in text
