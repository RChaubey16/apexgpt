"""POST /api/chat end to end with the real LLM, tools and corpus (F4.1).

Opt-in (spends free-tier quota):

    LLM_LIVE_TESTS=1 EMBEDDING_CACHE_DIR=../data/models uv run pytest -m llm
"""

import json
import os

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

pytestmark = pytest.mark.llm

if os.environ.get("LLM_LIVE_TESTS") != "1":
    pytest.skip("LLM_LIVE_TESTS=1 not set", allow_module_level=True)


def test_a_narrative_answer_streams_with_citations() -> None:
    app = create_app(Settings())
    if not app.state.orchestrator.llm.provider_names:
        pytest.skip("no LLM provider key configured")

    with TestClient(app) as client:
        response = client.post("/api/chat", json={"question": "Explain Abu Dhabi 2021"})

    events = []
    for block in response.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        events.append((lines["event"], json.loads(lines["data"])))
    kinds = [e for e, _ in events]
    assert kinds[-1] == "done", events[-1]
    assert kinds.count("token") > 1 and "citation" in kinds
    text = "".join(d["text"] for e, d in events if e == "token")
    assert "Verstappen" in text and "Hamilton" in text
    cited = {d["id"] for e, d in events if e == "citation"}
    assert cited == set(dict(events)["done"]["sources"])
