"""search_f1_knowledge without a database: arguments, payload, sources, errors."""

import pytest

from app.retrieval.errors import EmbeddingUnavailableError, SearchError
from app.retrieval.filters import SearchFilters
from app.retrieval.search import SearchResult
from app.tools import stats
from app.tools.base import ToolOutcome
from app.tools.knowledge import (
    MAX_QUERY_CHARS,
    MAX_TEXT_CHARS,
    NAME,
    InvalidArguments,
    KnowledgeTool,
    parse_arguments,
)
from app.tools.stats import StatsQueryRejected, StatsResult, StatsTool


def result(
    pageid: int, text: str = "Senna and Prost collided.", **extra
) -> SearchResult:
    values = {
        "pageid": pageid,
        "chunk_index": 0,
        "title": f"Article {pageid}",
        "section": "Race > Race report",
        "text": text,
        "source_url": f"https://en.wikipedia.org/?curid={pageid}",
        "season": 1989,
        "race_id": None,
        "score": 0.05,
        "signals": ("vector",),
        "rerank_score": 5.0,
    } | extra
    return SearchResult(**values)


class FakeRetriever:
    def __init__(self, results=None, error: Exception | None = None) -> None:
        self.results = results if results is not None else [result(1), result(2)]
        self.error = error
        self.calls: list[dict] = []

    def retrieve(self, session, query, *, filters=None, top_k=5):
        self.calls.append(
            {"session": session, "query": query, "filters": filters, "top_k": top_k}
        )
        if self.error:
            raise self.error
        return self.results


class FakeSession:
    def __init__(self) -> None:
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True


def make(retriever: FakeRetriever) -> tuple[KnowledgeTool, list[FakeSession]]:
    sessions: list[FakeSession] = []

    def factory() -> FakeSession:
        sessions.append(FakeSession())
        return sessions[-1]

    return KnowledgeTool(retriever, factory), sessions  # type: ignore[arg-type]


# --- arguments ---


@pytest.mark.parametrize(
    ("arguments", "query", "filters"),
    [
        ({"query": "Senna Prost Suzuka"}, "Senna Prost Suzuka", None),
        ({"query": "  Senna \n Prost  "}, "Senna Prost", None),
        (
            {"query": "Lauda crash", "seasons": [1976]},
            "Lauda crash",
            SearchFilters((1976,)),
        ),
        (
            {"query": "x", "seasons": [1990, 1989, 1990]},
            "x",
            SearchFilters((1989, 1990)),
        ),
        ({"query": "x", "seasons": []}, "x", None),
        ({"query": "x", "seasons": None}, "x", None),
        ({"query": "x", "limit": 50, "foo": "bar"}, "x", None),  # unknown keys ignored
    ],
)
def test_valid_arguments(arguments: dict, query: str, filters) -> None:
    assert parse_arguments(arguments) == (query, filters)


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (None, "object"),
        ("Senna", "object"),
        ([], "object"),
        ({}, "non-empty"),
        ({"query": "   "}, "non-empty"),
        ({"query": 42}, "non-empty"),
        ({"query": "x" * (MAX_QUERY_CHARS + 1)}, "at most"),
        ({"query": "x", "seasons": 1989}, "list of years"),
        ({"query": "x", "seasons": ["1989"]}, "list of years"),
        ({"query": "x", "seasons": [True]}, "list of years"),
        ({"query": "x", "seasons": [2026]}, "1950–2025"),
        ({"query": "x", "seasons": [1949]}, "1950–2025"),
        ({"query": "x", "seasons": list(range(1990, 2001))}, "at most 10"),
    ],
)
def test_invalid_arguments(arguments, message: str) -> None:
    with pytest.raises(InvalidArguments, match=message):
        parse_arguments(arguments)


# --- call ---


def test_results_become_a_payload_with_numbered_sources() -> None:
    retriever = FakeRetriever(
        [result(1), result(2, section=None, season=None, title="Prost–Senna rivalry")]
    )
    tool, sessions = make(retriever)

    outcome = tool.call(
        {"query": "Senna Prost Suzuka", "seasons": [1989]}, first_source_number=4
    )

    assert outcome.ok and outcome.name == NAME
    assert outcome.payload == {
        "results": [
            {"source": "S4", "title": "Article 1", "section": "Race > Race report",
             "season": 1989, "text": "Senna and Prost collided."},
            {"source": "S5", "title": "Prost–Senna rivalry", "section": None,
             "season": None, "text": "Senna and Prost collided."},
        ]
    }  # fmt: skip
    assert [(s.id, s.title, s.url, s.section, s.season) for s in outcome.sources] == [
        (
            "S4",
            "Article 1",
            "https://en.wikipedia.org/?curid=1",
            "Race > Race report",
            1989,
        ),
        ("S5", "Prost–Senna rivalry", "https://en.wikipedia.org/?curid=2", None, None),
    ]
    (call,) = retriever.calls
    assert call["query"] == "Senna Prost Suzuka" and call["top_k"] == 5
    assert call["filters"] == SearchFilters((1989,))
    assert call["session"] is sessions[0] and sessions[0].closed  # one session, closed


def test_urls_are_in_sources_not_the_payload() -> None:
    tool, _ = make(FakeRetriever())

    outcome = tool.call({"query": "x"})

    assert all("url" not in r for r in outcome.payload["results"])  # saves tokens
    assert outcome.sources[0].id == "S1"  # default numbering


def test_long_chunks_are_cut() -> None:
    tool, _ = make(FakeRetriever([result(1, text="y" * 5000)]))

    text = tool.call({"query": "x"}).payload["results"][0]["text"]

    assert len(text) == MAX_TEXT_CHARS + 1 and text.endswith("…")


def test_no_results_is_ok_with_a_hint() -> None:
    tool, _ = make(FakeRetriever([]))

    outcome = tool.call({"query": "zzz"})

    assert outcome.ok and outcome.sources == ()
    assert outcome.payload == {
        "results": [],
        "note": "nothing relevant found; try other search terms",
    }


def test_bad_arguments_are_an_error_payload_without_searching() -> None:
    retriever = FakeRetriever()
    tool, sessions = make(retriever)

    outcome = tool.call({"query": "x", "seasons": [2030]})

    assert outcome == ToolOutcome.error(NAME, outcome.payload["error"])
    assert not outcome.ok and "1950–2025" in outcome.payload["error"]
    assert retriever.calls == [] and sessions == []


@pytest.mark.parametrize(
    "error",
    [
        SearchError("Knowledge search is unavailable right now"),
        EmbeddingUnavailableError("The search model could not be loaded"),
        ValueError("query must not be empty"),  # e.g. only control characters
    ],
)
def test_search_failures_are_error_payloads(error: Exception) -> None:
    tool, sessions = make(FakeRetriever(error=error))

    outcome = tool.call({"query": "Senna"})

    assert not outcome.ok and outcome.payload == {"error": str(error)}
    assert sessions[0].closed


def test_unexpected_errors_are_not_swallowed() -> None:
    tool, _ = make(FakeRetriever(error=KeyError("bug")))

    with pytest.raises(KeyError):
        tool.call({"query": "Senna"})


def test_definition_for_the_llm() -> None:
    tool, _ = make(FakeRetriever())

    definition = tool.definition()

    function = definition["function"]
    assert definition["type"] == "function" and function["name"] == NAME == tool.name
    assert "query_stats" in function["description"]  # points numbers elsewhere
    params = function["parameters"]
    assert params["required"] == ["query"]
    assert params["properties"]["seasons"]["items"] == {"type": "integer"}


# --- StatsTool.call (the same interface) ---


def test_stats_call_returns_the_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = StatsTool(None)
    monkeypatch.setattr(
        tool, "run", lambda sql: StatsResult(sql, ("wins",), ((105,),), False, 3)
    )

    outcome = tool.call({"sql": "SELECT wins FROM v_driver_career"})

    assert outcome == ToolOutcome(
        stats.NAME, {"columns": ["wins"], "rows": [[105]], "row_count": 1}, ok=True
    )
    assert tool.name == "query_stats"


@pytest.mark.parametrize("arguments", [None, {}, {"sql": 5}, "SELECT 1"])
def test_stats_call_needs_sql(arguments) -> None:
    outcome = StatsTool(None).call(arguments)

    assert not outcome.ok and "'sql'" in outcome.payload["error"]


def test_stats_call_turns_tool_errors_into_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = StatsTool(None)

    def rejected(sql):
        raise StatsQueryRejected(
            "unknown table drivers; query only v_race_winners, ..."
        )

    monkeypatch.setattr(tool, "run", rejected)

    outcome = tool.call({"sql": "SELECT * FROM drivers"})
    unconfigured = StatsTool(None).call({"sql": "SELECT * FROM v_driver_career"})

    assert outcome.payload == {
        "error": "unknown table drivers; query only v_race_winners, ..."
    }
    assert not unconfigured.ok and "not configured" in unconfigured.payload["error"]


def test_stats_definition_needs_the_database() -> None:
    with pytest.raises(stats.StatsUnavailable):
        StatsTool(None).definition()
