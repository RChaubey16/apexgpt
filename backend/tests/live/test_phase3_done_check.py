"""Phase 3 done check: the three CLI questions from docs/archive/v1.0.0-mvp/MVP-PLAN.md, answered end
to end (entity resolution → LLM → tools → grounded, cited answer).

Opt-in: spends free-tier quota (~5-8k tokens per question) and needs the corpus,
the LLM key(s) and READONLY_DATABASE_URL:

    LLM_LIVE_TESTS=1 EMBEDDING_CACHE_DIR=../data/models uv run pytest -m llm

Checked on facts, not wording: the Monza record is shared (Hamilton and
Schumacher, 5); Abu Dhabi 2021 is the Verstappen/Hamilton title decider with
the safety-car restart; the 1976 title went to Hunt by 69 points to 68.
"""

import os

import pytest

from app.answer import Answer, build_orchestrator
from app.core.config import Settings

pytestmark = pytest.mark.llm

if os.environ.get("LLM_LIVE_TESTS") != "1":
    pytest.skip("LLM_LIVE_TESTS=1 not set", allow_module_level=True)

SETTINGS = Settings()
if SETTINGS.readonly_database_url is None:
    pytest.skip("READONLY_DATABASE_URL not set", allow_module_level=True)


@pytest.fixture(scope="module")
def orchestrator():
    orchestrator = build_orchestrator(SETTINGS)
    if not orchestrator._llm.provider_names:
        pytest.skip("no LLM provider key configured")
    return orchestrator


def _report(answer: Answer) -> str:
    calls = [(c.name, c.ok) for c in answer.tool_calls]
    return f"{answer.provider}/{answer.model} {calls}\n{answer.text}"


def test_most_wins_at_monza(orchestrator) -> None:
    answer = orchestrator.answer("Who has the most wins at Monza?")

    for fact in ("Hamilton", "Schumacher", "5"):
        assert fact in answer.text, _report(answer)
    assert any(c.name == "query_stats" and c.ok for c in answer.tool_calls), _report(
        answer
    )


def test_explain_abu_dhabi_2021(orchestrator) -> None:
    answer = orchestrator.answer("Explain Abu Dhabi 2021")

    for fact in ("Verstappen", "Hamilton"):
        assert fact in answer.text, _report(answer)
    assert "safety car" in answer.text.lower().replace("-", " "), _report(answer)
    assert "2021 Abu Dhabi Grand Prix" in {s.title for s in answer.sources}, _report(
        answer
    )


def test_hunt_beat_lauda_1976_with_final_points(orchestrator) -> None:
    answer = orchestrator.answer(
        "How did Hunt beat Lauda in 1976 and what were the final points?"
    )

    for fact in ("Hunt", "Lauda", "69", "68"):
        assert fact in answer.text, _report(answer)
    used = {c.name for c in answer.tool_calls if c.ok}
    assert {"query_stats", "search_f1_knowledge"} <= used, _report(answer)
    assert answer.sources, _report(answer)  # the narrative part is cited
