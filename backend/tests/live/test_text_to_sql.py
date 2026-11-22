"""Text-to-SQL end to end: the real LLM writes SQL from the tool definition, the
stats tool runs it (F3.5).

Opt-in (spends free-tier quota; needs a provider key and READONLY_DATABASE_URL):

    LLM_LIVE_TESTS=1 uv run pytest -m llm

Answers are checked in the returned rows, not the wording. When F3.5 was
built, Groq's gpt-oss-120b wrote correct SQL for 8/8 such questions at the
first attempt. Five questions keep this under the free tier's per-minute limit.
"""

import json
import os

import pytest

from app.core.config import Settings
from app.llm import build_llm_client
from app.tools.stats import StatsTool, tool_definition

pytestmark = pytest.mark.llm

if os.environ.get("LLM_LIVE_TESTS") != "1":
    pytest.skip("LLM_LIVE_TESTS=1 not set", allow_module_level=True)

SETTINGS = Settings()
if SETTINGS.readonly_database_url is None:
    pytest.skip("READONLY_DATABASE_URL not set", allow_module_level=True)

QUESTIONS = {
    "Who has the most Formula 1 race wins of all time?": ["Lewis Hamilton", "105"],
    "Who has the most wins at Monza?": ["Hamilton", "Schumacher", "5"],
    "Who won the 1976 drivers' championship?": ["James Hunt"],
    "How many races did Ayrton Senna win?": ["41"],
    "Which constructor won the 2009 constructors' championship?": ["Brawn"],
}


@pytest.fixture(scope="module")
def tool():
    tool = StatsTool.from_settings(SETTINGS)
    yield tool
    tool.dispose()


@pytest.mark.parametrize(
    ("question", "expected"), QUESTIONS.items(), ids=list(QUESTIONS)
)
def test_the_llm_writes_sql_the_tool_answers(
    tool: StatsTool, question: str, expected: list[str]
) -> None:
    llm = build_llm_client(SETTINGS)
    if not llm.provider_names:
        pytest.skip("no LLM provider key configured")

    response = llm.complete(
        [
            {
                "role": "system",
                "content": "Answer Formula 1 statistics questions by calling "
                "query_stats with one PostgreSQL query.",
            },
            {"role": "user", "content": question},
        ],
        tools=[tool_definition(tool.schema())],
        tool_choice="required",
        temperature=0,
        max_tokens=1500,
    )

    call, *_ = response.tool_calls
    result = tool.run(call.arguments["sql"])
    rows = json.dumps(result.to_payload()["rows"][:5], ensure_ascii=False)
    for value in expected:
        assert value in rows, (call.arguments["sql"], rows)
