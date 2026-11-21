import pytest

from app.retrieval import __main__ as cli
from app.retrieval.errors import SearchError
from app.retrieval.filters import NO_FILTERS, SearchFilters
from app.retrieval.retriever import CANDIDATES, TOP_K
from app.retrieval.search import SearchResult
from tests.conftest import make_settings


def result(
    title: str, section: str | None, text: str, rerank_score: float | None = 5.19
) -> SearchResult:
    return SearchResult(
        pageid=1,
        chunk_index=0,
        title=title,
        section=section,
        text=text,
        source_url="https://en.wikipedia.org/wiki/1989_Japanese_Grand_Prix",
        season=1989,
        race_id=None,
        score=0.0464,
        signals=("vector", "article"),
        rerank_score=rerank_score,
    )


class FakeRetriever:
    def __init__(self, results: list[SearchResult] | Exception) -> None:
        self.results = results
        self.calls: list[dict] = []

    def retrieve(self, session, query, *, filters=None, top_k=5):
        self.calls.append({"query": query, "filters": filters, "top_k": top_k})
        if isinstance(self.results, Exception):
            raise self.results
        return self.results


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch):
    """Never touches a database or a model: the engine is lazy, retrieval is faked."""
    state: dict = {
        "retriever": FakeRetriever(
            [
                result("1989 Japanese Grand Prix", "Race > Race report", "x" * 500),
                result("Prost–Senna rivalry", None, "Short lead."),
            ]
        ),
        "rerank": [],
    }

    def fake_build(settings, *, rerank=True):
        state["rerank"].append(rerank)
        return state["retriever"]

    monkeypatch.setattr(cli, "get_settings", lambda: make_settings())
    monkeypatch.setattr(cli, "build_retriever", fake_build)
    return state


def test_prints_the_reranked_top_5(fake, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.run(["Senna Prost Suzuka collision 1989"]) == 0

    out = capsys.readouterr().out
    assert "2 results in" in out
    assert "(season filter: 1989; reranked: yes)" in out
    assert " 1. 1989 Japanese Grand Prix > Race > Race report" in out
    assert " 2. Prost–Senna rivalry\n" in out
    assert "0.0464  rerank 5.19  [vector, article]" in out
    assert "x" * cli.PREVIEW_CHARS + "…" in out and "x" * 161 not in out
    assert "Short lead.\n" in out  # short text: no ellipsis
    call = fake["retriever"].calls[0]
    assert call["filters"] == SearchFilters(seasons=(1989,))
    assert call["top_k"] == TOP_K
    assert fake["rerank"] == [True]


def test_no_rerank_builds_a_retriever_without_the_reranker(
    fake, capsys: pytest.CaptureFixture[str]
) -> None:
    fake["retriever"] = FakeRetriever([result("Monaco", None, "Street circuit.", None)])

    cli.run(["q", "--no-rerank", "--limit", "10"])

    out = capsys.readouterr().out
    assert fake["rerank"] == [False]
    assert "reranked: no" in out and "rerank " not in out.split("\n", 2)[2]
    assert fake["retriever"].calls[0]["top_k"] == 10


def test_show_text_prints_whole_chunks(
    fake, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.run(["q", "--show-text"])

    assert "x" * 500 in capsys.readouterr().out


def test_season_and_no_filter_options(fake) -> None:
    cli.run(["Lauda 1976", "--season", "1977", "--season", "1976"])
    cli.run(["Lauda 1976", "--no-filters"])

    calls = fake["retriever"].calls
    assert calls[0]["filters"] == SearchFilters(seasons=(1976, 1977))
    assert calls[1]["filters"] == NO_FILTERS


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["  "], "must not be empty"),
        (["q", "--limit", "0"], "--limit"),
        (["q", "--limit", str(CANDIDATES + 1)], "--limit"),
        (["q", "--season", "2026"], "outside"),
    ],
)
def test_bad_input_exits_2_without_searching(
    argv: list[str], message: str, fake, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.run(argv) == 2
    assert message in capsys.readouterr().err
    assert fake["retriever"].calls == [] and fake["rerank"] == []


def test_season_and_no_filters_are_exclusive(fake) -> None:
    with pytest.raises(SystemExit) as info:
        cli.run(["q", "--season", "1976", "--no-filters"])
    assert info.value.code == 2


def test_search_errors_exit_1_with_the_safe_message(
    fake, capsys: pytest.CaptureFixture[str]
) -> None:
    fake["retriever"] = FakeRetriever(
        SearchError("Knowledge search is unavailable right now")
    )

    assert cli.run(["q"]) == 1
    assert "error: Knowledge search is unavailable right now" in capsys.readouterr().err
