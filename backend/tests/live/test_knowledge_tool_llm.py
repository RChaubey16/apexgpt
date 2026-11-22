"""search_f1_knowledge with the real LLM: the model's own search terms (F3.6).

Opt-in (spends free-tier quota; needs a provider key, DATABASE_URL with the
corpus and EMBEDDING_CACHE_DIR):

    LLM_LIVE_TESTS=1 EMBEDDING_CACHE_DIR=../data/models uv run pytest -m llm
"""

import os

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.session import create_db_engine
from app.llm import build_llm_client
from app.tools.knowledge import build_knowledge_tool, parse_arguments

pytestmark = pytest.mark.llm

if os.environ.get("LLM_LIVE_TESTS") != "1":
    pytest.skip("LLM_LIVE_TESTS=1 not set", allow_module_level=True)

SETTINGS = Settings()
QUESTIONS = {
    "Explain what happened at Abu Dhabi in 2021.": {"2021 Abu Dhabi Grand Prix"},
    "What happened between Senna and Prost at Suzuka in 1989?": {"1989 Japanese Grand Prix"},
    "How did Hunt beat Lauda to the 1976 title?": {
        "James Hunt", "Niki Lauda", "Hunt–Lauda rivalry",
        "1976 Japanese Grand Prix", "1976 Formula One season",
    },
}  # fmt: skip


@pytest.fixture(scope="module")
def tool():
    engine = create_db_engine(SETTINGS)
    yield build_knowledge_tool(SETTINGS, sessionmaker(bind=engine))
    engine.dispose()


@pytest.mark.parametrize(("question", "any_of"), QUESTIONS.items(), ids=list(QUESTIONS))
def test_the_llm_searches_with_useful_terms(
    tool, question: str, any_of: set[str]
) -> None:
    llm = build_llm_client(SETTINGS)
    if not llm.provider_names:
        pytest.skip("no LLM provider key configured")

    response = llm.complete(
        [
            {
                "role": "system",
                "content": "Answer Formula 1 history questions using the search tool.",
            },
            {"role": "user", "content": question},
        ],
        tools=[tool.definition()],
        tool_choice="required",
        temperature=0,
        max_tokens=800,
    )

    call, *_ = response.tool_calls
    parse_arguments(call.arguments)  # the model's arguments validate
    outcome = tool.call(call.arguments)
    titles = {s.title for s in outcome.sources}
    assert outcome.ok and titles & any_of, (call.arguments, titles)
