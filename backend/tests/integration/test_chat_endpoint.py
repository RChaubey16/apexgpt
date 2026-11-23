"""POST /api/chat over real Postgres (F4.1): the real stats tool, run as the
read-only role, behind a scripted LLM. Checks the whole path from HTTP to the
database and back as SSE.

Skipped unless TEST_DATABASE_URL is set (see test_database.py for the warning).
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.answer.orchestrator import Orchestrator
from app.api.routes.chat import get_orchestrator
from app.main import create_app
from app.tools.stats import StatsTool
from tests.answer.test_orchestrator import ScriptedLLM, call, reply
from tests.conftest import make_settings
from tests.integration import test_stats_tool as stats_fixtures

pytestmark = pytest.mark.integration

# A migrated schema with committed data (two Monza races: one win each for
# Senna and Berger), and an engine acting as apexgpt_llm_reader.
admin = stats_fixtures.admin
reader_engine = stats_fixtures.reader_engine


def frames(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_chat_runs_a_real_stats_query_and_streams_the_rows(reader_engine) -> None:
    llm = ScriptedLLM(
        reply(
            None,
            call(
                "query_stats",
                1,
                sql="SELECT driver_name, count(*) AS wins FROM v_race_winners "
                "WHERE circuit_name ILIKE '%monza%' GROUP BY 1 ORDER BY 2 DESC, 1",
            ),
        ),
        reply("Ayrton Senna and Gerhard Berger have one Monza win each."),
    )
    app = create_app(make_settings(environment="test"))
    app.dependency_overrides[get_orchestrator] = lambda: Orchestrator(
        llm, [StatsTool(reader_engine)]  # type: ignore[arg-type]
    )

    response = TestClient(app).post("/api/chat", json={"question": "Most Monza wins?"})

    events = frames(response.text)
    assert [e for e, _ in events][:3] == ["tool", "tool", "table"]
    table = dict(events)["table"]
    assert table == {
        "columns": ["driver_name", "wins"],
        "rows": [["Ayrton Senna", 1], ["Gerhard Berger", 1]],
    }
    tokens = "".join(d["text"] for e, d in events if e == "token")
    assert tokens == "Ayrton Senna and Gerhard Berger have one Monza win each."
    assert events[-1][0] == "done" and events[-1][1]["tools"] == [
        {"name": "query_stats", "ok": True}
    ]
    # The rows went back to the model too.
    tool_message = llm.requests[1]["messages"][-1]
    assert json.loads(tool_message["content"])["rows"] == [
        ["Ayrton Senna", 1],
        ["Gerhard Berger", 1],
    ]


def test_a_rejected_query_is_reported_to_the_model_not_the_user(reader_engine) -> None:
    llm = ScriptedLLM(
        reply(None, call("query_stats", 1, sql="SELECT * FROM drivers")),
        reply("I couldn't look that up."),
    )
    app = create_app(make_settings(environment="test"))
    app.dependency_overrides[get_orchestrator] = lambda: Orchestrator(
        llm, [StatsTool(reader_engine)]  # type: ignore[arg-type]
    )

    events = frames(TestClient(app).post("/api/chat", json={"question": "q"}).text)

    assert (
        "tool",
        {"name": "query_stats", "status": "finished", "ok": False},
    ) in events
    assert "table" not in [e for e, _ in events]
    assert "unknown table drivers" in llm.requests[1]["messages"][-1]["content"]
    assert events[-1][0] == "done"


def test_a_follow_up_is_condensed_then_answered_from_the_database(
    reader_engine,
) -> None:
    from tests.answer.test_orchestrator import CondensingLLM

    llm = CondensingLLM(
        "How many times did Ayrton Senna win at Monza?",
        reply(
            None,
            call(
                "query_stats",
                1,
                sql="SELECT count(*) AS wins FROM v_race_winners "
                "WHERE circuit_name ILIKE '%monza%' AND driver_name = 'Ayrton Senna'",
            ),
        ),
        reply("Ayrton Senna won once at Monza."),
    )
    app = create_app(make_settings(environment="test"))
    app.dependency_overrides[get_orchestrator] = lambda: Orchestrator(
        llm, [StatsTool(reader_engine)]  # type: ignore[arg-type]
    )
    body = {
        "question": "How many times did he win there?",
        "history": [
            {"role": "user", "content": "Who won at Monza?"},
            {"role": "assistant", "content": "Ayrton Senna and Gerhard Berger."},
        ],
    }

    events = frames(TestClient(app).post("/api/chat", json=body).text)

    assert events[0] == (
        "question",
        {"text": "How many times did Ayrton Senna win at Monza?"},
    )
    assert dict(events)["table"] == {"columns": ["wins"], "rows": [[1]]}
    assert events[-1][0] == "done"
    assert events[-1][1]["question"] == "How many times did Ayrton Senna win at Monza?"
    assert "Who won at Monza?" in llm.completions[0][1]["content"]
