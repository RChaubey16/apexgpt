import pytest

from app.retrieval import __main__ as cli
from app.retrieval.errors import SearchError
from app.retrieval.filters import NO_FILTERS, SearchFilters
from app.retrieval.search import SearchResult
from tests.conftest import make_settings


def result(title: str, section: str | None, text: str) -> SearchResult:
    return SearchResult(
        pageid=1,
        chunk_index=0,
        title=title,
        section=section,
        text=text,
        source_url="https://en.wikipedia.org/wiki/1989_Japanese_Grand_Prix",
        season=1989,
        race_id=None,
        score=0.0246,
        signals=("vector", "article"),
    )


@pytest.fixture
def searched(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Never touches a database: the engine is lazy and search is replaced."""
    calls: list[dict] = []

    def fake_search(self, session, query, *, filters=None, limit=10):
        calls.append({"query": query, "filters": filters, "limit": limit})
        return [
            result("1989 Japanese Grand Prix", "Race > Race report", "x" * 500),
            result("Prost–Senna rivalry", None, "Short lead."),
        ]

    monkeypatch.setattr(cli, "get_settings", lambda: make_settings())
    monkeypatch.setattr(cli.HybridSearcher, "search", fake_search)
    return calls


def test_prints_ranked_results(
    searched: list[dict], capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.run(["Senna Prost Suzuka collision 1989"]) == 0

    out = capsys.readouterr().out
    assert "2 results in" in out and "(season filter: 1989)" in out
    assert " 1. 1989 Japanese Grand Prix > Race > Race report" in out
    assert " 2. Prost–Senna rivalry\n" in out
    assert "[vector, article]" in out
    assert "x" * cli.PREVIEW_CHARS + "…" in out and "x" * 161 not in out
    assert "Short lead.\n" in out  # short text: no ellipsis
    assert searched[0]["filters"] == SearchFilters(seasons=(1989,))
    assert searched[0]["limit"] == 10


def test_show_text_prints_whole_chunks(
    searched: list[dict], capsys: pytest.CaptureFixture[str]
) -> None:
    cli.run(["q", "--show-text"])

    assert "x" * 500 in capsys.readouterr().out


def test_season_and_no_filter_options(searched: list[dict]) -> None:
    cli.run(["Lauda 1976", "--season", "1977", "--season", "1976", "--limit", "3"])
    cli.run(["Lauda 1976", "--no-filters"])

    assert searched[0]["filters"] == SearchFilters(seasons=(1976, 1977))
    assert searched[0]["limit"] == 3
    assert searched[1]["filters"] == NO_FILTERS


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["  "], "must not be empty"),
        (["q", "--limit", "0"], "--limit"),
        (["q", "--limit", "51"], "--limit"),
        (["q", "--season", "2026"], "outside"),
    ],
)
def test_bad_input_exits_2_without_searching(
    argv: list[str],
    message: str,
    searched: list[dict],
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.run(argv) == 2
    assert message in capsys.readouterr().err
    assert searched == []


def test_season_and_no_filters_are_exclusive(searched: list[dict]) -> None:
    with pytest.raises(SystemExit) as info:
        cli.run(["q", "--season", "1976", "--no-filters"])
    assert info.value.code == 2


def test_search_errors_exit_1_with_the_safe_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def failing(self, session, query, *, filters=None, limit=10):
        raise SearchError("Knowledge search is unavailable right now")

    monkeypatch.setattr(cli, "get_settings", lambda: make_settings())
    monkeypatch.setattr(cli.HybridSearcher, "search", failing)

    assert cli.run(["q"]) == 1
    assert "error: Knowledge search is unavailable right now" in capsys.readouterr().err
