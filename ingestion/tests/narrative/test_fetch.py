import logging
from pathlib import Path

import pytest

from common import http as common_http
from narrative import __main__ as cli
from narrative.cache import ArticleCache
from narrative.config import WikiSettings
from narrative.fetch import fetch_articles
from narrative.wiki import Article, WikiClient
from tests.narrative.fake_wiki import FakeWiki


@pytest.fixture(autouse=True)
def no_http_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(common_http.time, "sleep", lambda s: None)


@pytest.fixture
def fake() -> FakeWiki:
    w = FakeWiki()
    w.add("Ayrton Senna", 1, 101, "<p>Senna</p>")
    w.add("Michael Schumacher", 2, 202)
    w.redirects["Schumi"] = "Michael Schumacher"
    return w


@pytest.fixture
def client(fake: FakeWiki) -> WikiClient:
    return WikiClient("ua", 0.1, opener=fake, clock=lambda: 0.0, sleep=lambda s: None)


@pytest.fixture
def cache(tmp_path: Path) -> ArticleCache:
    return ArticleCache(tmp_path / "wikipedia")


# --- cache ---


def test_cache_round_trip(cache: ArticleCache) -> None:
    article = Article("Schumi", "Michael Schumacher", 2, 202, "<p>ü</p>")

    path = cache.put(article)

    assert cache.get("Schumi") == article
    assert path.name.startswith("schumi-") and path.suffix == ".json"
    assert not list(cache.directory.glob(".tmp-*"))


def test_cache_paths_are_unique_per_title(cache: ArticleCache) -> None:
    paths = {cache.path_for(t) for t in ("AB", "Ab", "A B", "A-B", "A/B")}

    assert len(paths) == 5


def test_unreadable_cache_file_is_ignored(cache: ArticleCache) -> None:
    cache.directory.mkdir(parents=True)
    cache.path_for("Ayrton Senna").write_text("{not json")

    assert cache.get("Ayrton Senna") is None


def test_cache_file_for_another_title_is_ignored(cache: ArticleCache) -> None:
    cache.put(Article("Ayrton Senna", "Ayrton Senna", 1, 101, "x"))
    other = (
        cache.path_for("Ayrton Senna")
        .read_text()
        .replace('"requested_title": "Ayrton Senna"', '"requested_title": "Other"')
    )
    cache.path_for("Ayrton Senna").write_text(other)

    assert cache.get("Ayrton Senna") is None


# --- fetch ---


def test_first_fetch_downloads_and_caches(
    fake: FakeWiki, client: WikiClient, cache: ArticleCache
) -> None:
    report = fetch_articles(["Ayrton Senna", "Schumi", "Nope"], client, cache)

    assert (report.fetched, report.missing) == (["Ayrton Senna", "Schumi"], ["Nope"])
    assert cache.get("Schumi").title == "Michael Schumacher"
    assert cache.get("Ayrton Senna").html == "<p>Senna</p>"


def test_cached_articles_are_not_refetched(
    fake: FakeWiki, client: WikiClient, cache: ArticleCache
) -> None:
    fetch_articles(["Ayrton Senna", "Schumi"], client, cache)
    fake.calls.clear()

    report = fetch_articles(["Ayrton Senna", "Schumi"], client, cache)

    assert report.unchanged == ["Ayrton Senna", "Schumi"]
    assert fake.calls == []


def test_duplicate_and_unnormalised_titles_are_fetched_once(
    fake: FakeWiki, client: WikiClient, cache: ArticleCache
) -> None:
    report = fetch_articles(["Ayrton Senna", "ayrton_senna"], client, cache)

    # "ayrton_senna" normalises to "Ayrton senna", a different title from "Ayrton Senna".
    assert report.fetched == ["Ayrton Senna"]
    assert report.missing == ["Ayrton senna"]


def test_refresh_refetches_only_changed_revisions(
    fake: FakeWiki, client: WikiClient, cache: ArticleCache
) -> None:
    fetch_articles(["Ayrton Senna", "Schumi"], client, cache)
    fake.add("Michael Schumacher", 2, 203, "<p>edited</p>")  # new revision
    fake.calls.clear()

    report = fetch_articles(["Ayrton Senna", "Schumi"], client, cache, refresh=True)

    assert (report.unchanged, report.updated) == (["Ayrton Senna"], ["Schumi"])
    assert [c["action"] for c in fake.calls] == ["query", "parse"]
    assert cache.get("Schumi").revid == 203
    assert cache.get("Schumi").html == "<p>edited</p>"


def test_refresh_keeps_cached_copy_of_deleted_page(
    fake: FakeWiki, client: WikiClient, cache: ArticleCache
) -> None:
    fetch_articles(["Ayrton Senna"], client, cache)
    del fake.pages["Ayrton Senna"]

    report = fetch_articles(["Ayrton Senna"], client, cache, refresh=True)

    assert report.missing == ["Ayrton Senna"]
    assert cache.get("Ayrton Senna") is not None


def test_refresh_skips_parse_for_pages_that_dont_exist(
    fake: FakeWiki, client: WikiClient, cache: ArticleCache
) -> None:
    report = fetch_articles(["Nope"], client, cache, refresh=True)

    assert report.missing == ["Nope"]
    assert [c["action"] for c in fake.calls] == ["query"]


def test_summary(fake: FakeWiki, client: WikiClient, cache: ArticleCache) -> None:
    report = fetch_articles(["Ayrton Senna", "Nope"], client, cache)

    assert report.summary() == "1 fetched, 0 updated, 0 cached, 1 missing"


# --- settings and CLI ---


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setitem(WikiSettings.model_config, "env_file", None)
    monkeypatch.delenv("WIKI_USER_AGENT", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


def test_cli_requires_a_user_agent(
    isolated_env: Path, caplog: pytest.LogCaptureFixture
) -> None:
    assert cli.run(["--title", "Ayrton Senna"]) == 2
    assert "WIKI_USER_AGENT is not set" in caplog.text


@pytest.mark.parametrize(
    ("env", "value"),
    [
        ("WIKI_USER_AGENT", "bad\nagent"),
        ("WIKI_MIN_INTERVAL_SECONDS", "0"),
        ("WIKI_MIN_INTERVAL_SECONDS", "61"),
    ],
)
def test_invalid_settings(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch, env: str, value: str
) -> None:
    monkeypatch.setenv("WIKI_USER_AGENT", "ok-agent")
    monkeypatch.setenv(env, value)

    assert cli.run(["--title", "A"]) == 2


@pytest.mark.parametrize(
    "args", [[], ["--title", "A|B"], ["--titles-file", "/nope.txt"]]
)
def test_cli_rejects_bad_arguments(isolated_env: Path, args: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.run(args)
    assert exc.value.code == 2


def test_cli_fetches_into_data_dir(
    isolated_env: Path,
    fake: FakeWiki,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    monkeypatch.setenv("WIKI_USER_AGENT", "ok-agent/1.0")
    monkeypatch.setattr(
        cli,
        "WikiClient",
        lambda ua, interval: WikiClient(
            ua, interval, opener=fake, clock=lambda: 0.0, sleep=lambda s: None
        ),
    )
    titles = isolated_env / "titles.txt"
    titles.write_text("# drivers\nAyrton Senna\n\nSchumi\nNope\n")

    assert cli.run(["--titles-file", str(titles), "--title", "Ayrton Senna"]) == 0

    assert "2 fetched, 0 updated, 0 cached, 1 missing" in caplog.text
    assert "Not on Wikipedia: Nope" in caplog.text
    assert ArticleCache(isolated_env / "wikipedia").get("Schumi") is not None
    assert fake.user_agents[0] == "ok-agent/1.0"
