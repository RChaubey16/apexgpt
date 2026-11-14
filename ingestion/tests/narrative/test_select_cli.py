import contextlib
import logging
from pathlib import Path

import psycopg
import pytest

from common import http as common_http
from narrative import __main__ as fetch_cli
from narrative import select as cli
from narrative.cache import ArticleCache
from narrative.config import WikiSettings
from narrative.manifest import manifest_path, read_manifest, write_manifest
from narrative.selection import (
    Depth,
    DriverRow,
    EntityRows,
    Kind,
    RaceRow,
    Selected,
)
from narrative.wiki import WikiClient
from structured.config import Settings
from tests.narrative.fake_wiki import FakeWiki

W = "https://en.wikipedia.org/wiki/"


@pytest.fixture(autouse=True)
def no_http_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(common_http.time, "sleep", lambda s: None)


@pytest.fixture(autouse=True)
def no_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """The real title_overrides.csv names refs these fake rows don't have."""
    path = tmp_path / "no_overrides.csv"
    path.write_text("kind,ref,title\n")
    monkeypatch.setattr(cli, "OVERRIDES_FILE", path)
    return path


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """No repo .env; a temp DATA_DIR; a DB URL and user agent set."""
    monkeypatch.setitem(WikiSettings.model_config, "env_file", None)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:secret-pw@localhost:1/db")
    monkeypatch.setenv("WIKI_USER_AGENT", "test-agent/1.0")
    return tmp_path


@pytest.fixture
def topics(tmp_path: Path) -> Path:
    path = tmp_path / "topics.yaml"
    path.write_text(
        "iconic_race:\n  - title: 1989 Japanese Grand Prix\n    drivers: [senna]\n"
    )
    return path


ROWS = EntityRows(
    races=[
        RaceRow(480, 1989, 22, "Japanese Grand Prix", W + "1989_Japanese_Grand_Prix"),
        RaceRow(481, 1989, 29, "Gone Grand Prix", W + "1989_Gone_Grand_Prix"),
    ],
    driver_refs={"senna": 102},
)


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Fake connect + entity rows; records the URL it was given."""
    urls: list[str] = []

    @contextlib.contextmanager
    def connect(url: str, timeout: int):
        urls.append(url)
        yield object()

    monkeypatch.setattr(cli, "connect", connect)
    monkeypatch.setattr(cli, "read_entity_rows", lambda conn: ROWS)
    return urls


@pytest.fixture
def wiki(monkeypatch: pytest.MonkeyPatch) -> FakeWiki:
    fake = FakeWiki()
    fake.add("1989 Japanese Grand Prix", 1, 100, "<p>Suzuka</p>")

    def client(ua: str, interval: float) -> WikiClient:
        return WikiClient(
            ua, interval, opener=fake, clock=lambda: 0.0, sleep=lambda s: 0
        )

    monkeypatch.setattr(cli, "WikiClient", client)
    monkeypatch.setattr(fetch_cli, "WikiClient", client)
    return fake


def test_select_resolves_and_writes_the_manifest(
    env: Path,
    topics: Path,
    db: list[str],
    wiki: FakeWiki,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    assert cli.run(["--topics", str(topics)]) == 0

    (article,) = read_manifest(manifest_path(env)).articles
    assert article.title == "1989 Japanese Grand Prix"
    assert (article.depth, article.kinds) == (Depth.FULL, (Kind.RACE, Kind.TOPIC))
    assert (article.race_id, article.driver_ids, article.pageid) == (480, (102,), 1)
    assert "Dropped 1 articles (not on Wikipedia)" in caplog.text
    assert "'1989 Gone Grand Prix' (race, race)" in caplog.text
    assert wiki.user_agents == ["test-agent/1.0"]
    assert "secret-pw" not in caplog.text
    assert db == ["postgresql://u:secret-pw@localhost:1/db"]


def test_no_resolve_is_offline_and_writes_nothing(
    env: Path,
    topics: Path,
    db: list[str],
    wiki: FakeWiki,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    assert cli.run(["--topics", str(topics), "--no-resolve"]) == 0

    assert wiki.calls == []
    assert not manifest_path(env).exists()
    assert "2 articles" in caplog.text
    assert "by depth: full 1, race 1, circuit 0, lead 0" in caplog.text


def test_no_resolve_works_without_a_user_agent(
    env: Path, topics: Path, db: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("WIKI_USER_AGENT")
    assert cli.run(["--topics", str(topics), "--no-resolve"]) == 0


def test_output_path(env: Path, topics: Path, db: list[str], wiki: FakeWiki) -> None:
    out = env / "elsewhere" / "sel.json"
    assert cli.run(["--topics", str(topics), "--output", str(out)]) == 0
    assert len(read_manifest(out).articles) == 1


@pytest.mark.parametrize(
    ("unset", "message"),
    [
        ("DATABASE_URL", "DATABASE_URL is not set"),
        ("WIKI_USER_AGENT", "WIKI_USER_AGENT"),
    ],
)
def test_required_settings(
    env: Path,
    topics: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    unset: str,
    message: str,
) -> None:
    monkeypatch.delenv(unset)
    assert cli.run(["--topics", str(topics)]) == 2
    assert message in caplog.text


def test_invalid_database_url_is_not_echoed(
    env: Path,
    topics: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "mysql://u:hunter2@h/db")
    assert cli.run(["--topics", str(topics)]) == 2
    assert "hunter2" not in caplog.text


def test_bad_topics_file(
    env: Path, tmp_path: Path, db: list[str], caplog: pytest.LogCaptureFixture
) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("gossip:\n  - title: A\n")
    assert cli.run(["--topics", str(bad), "--no-resolve"]) == 1
    assert "unknown group 'gossip'" in caplog.text


def test_topic_missing_on_wikipedia_fails_and_writes_nothing(
    env: Path,
    tmp_path: Path,
    db: list[str],
    wiki: FakeWiki,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = tmp_path / "t.yaml"
    path.write_text("concept:\n  - title: Not A Real Article\n")
    assert cli.run(["--topics", str(path)]) == 1
    assert "'Not A Real Article' is not on Wikipedia" in caplog.text
    assert not manifest_path(env).exists()


def test_database_errors_show_the_class_only(
    env: Path,
    topics: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def refuse(url: str, timeout: int):
        raise psycopg.OperationalError("connection to u:secret-pw failed")

    monkeypatch.setattr(cli, "connect", refuse)
    assert cli.run(["--topics", str(topics)]) == 1
    assert "Database error: OperationalError" in caplog.text
    assert "secret-pw" not in caplog.text


def test_empty_database(
    env: Path,
    topics: Path,
    db: list[str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(cli, "read_entity_rows", lambda conn: EntityRows())
    assert cli.run(["--topics", str(topics)]) == 1
    assert "load the structured data first" in caplog.text


def test_unwritable_output(
    env: Path,
    topics: Path,
    db: list[str],
    wiki: FakeWiki,
    caplog: pytest.LogCaptureFixture,
) -> None:
    blocker = env / "file"
    blocker.write_text("")
    assert cli.run(["--topics", str(topics), "--output", str(blocker / "s.json")]) == 1
    assert "Cannot write" in caplog.text


# --- python -m narrative --selection ---


def _manifest(env: Path) -> Path:
    path = manifest_path(env)
    write_manifest(
        path,
        [
            Selected(
                title="1989 Japanese Grand Prix",
                kinds=(Kind.RACE,),
                depth=Depth.RACE,
                pageid=1,
            )
        ],
    )
    return path


def test_fetch_selection_uses_the_default_manifest(
    env: Path, wiki: FakeWiki, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    _manifest(env)

    assert fetch_cli.run(["--selection"]) == 0

    assert "1 articles in selection.json" in caplog.text
    assert ArticleCache(env / "wikipedia").get("1989 Japanese Grand Prix") is not None


def test_fetch_selection_with_a_path_and_extra_titles(
    env: Path, wiki: FakeWiki, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    wiki.add("Ayrton Senna", 2, 200)
    moved = env / "moved.json"
    _manifest(env).rename(moved)

    assert fetch_cli.run(["--selection", str(moved), "--title", "Ayrton Senna"]) == 0
    assert "2 fetched" in caplog.text


def test_fetch_selection_without_a_manifest(
    env: Path, wiki: FakeWiki, caplog: pytest.LogCaptureFixture
) -> None:
    assert fetch_cli.run(["--selection"]) == 1
    assert "run `python -m narrative.select` first" in caplog.text
    assert wiki.calls == []


# --- title overrides ---


def test_overrides_fix_stale_urls_end_to_end(
    env: Path,
    tmp_path: Path,
    db: list[str],
    wiki: FakeWiki,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    rows = EntityRows(
        races=ROWS.races[:1],
        drivers=[DriverRow(5, "Tony Brooks", W + "Tony_Brooks", wins=6)],
        driver_refs={"brooks": 5},
    )
    monkeypatch.setattr(cli, "read_entity_rows", lambda conn: rows)
    wiki.add("Tony Brooks", 7, 700, disambiguation=True)
    wiki.add("Tony Brooks (racing driver)", 8, 800)
    topics = tmp_path / "t.yaml"
    topics.write_text("concept:\n  - title: 1989 Japanese Grand Prix\n")
    overrides = tmp_path / "o.csv"

    # Without an override the driver is dropped, and the log says how to fix it.
    overrides.write_text("kind,ref,title\n")
    assert cli.run(["--topics", str(topics), "--overrides", str(overrides)]) == 0
    assert "add the right title to title_overrides.csv" in caplog.text
    assert "'Tony Brooks' (driver, full)" in caplog.text

    overrides.write_text("kind,ref,title\ndriver,brooks,Tony Brooks (racing driver)\n")
    assert cli.run(["--topics", str(topics), "--overrides", str(overrides)]) == 0
    titles = {a.title: a for a in read_manifest(manifest_path(env)).articles}
    assert titles["Tony Brooks (racing driver)"].driver_ids == (5,)
    assert titles["Tony Brooks (racing driver)"].depth == Depth.FULL


def test_override_to_a_missing_page_fails(
    env: Path,
    topics: Path,
    tmp_path: Path,
    db: list[str],
    wiki: FakeWiki,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    rows = EntityRows(
        races=ROWS.races[:1],
        drivers=[DriverRow(5, "Tony Brooks", W + "Tony_Brooks")],
        driver_refs={"brooks": 5, "senna": 102},
    )
    monkeypatch.setattr(cli, "read_entity_rows", lambda conn: rows)
    overrides = tmp_path / "o.csv"
    overrides.write_text("kind,ref,title\ndriver,brooks,Tony Brooks (typo)\n")

    assert cli.run(["--topics", str(topics), "--overrides", str(overrides)]) == 1
    assert "'Tony Brooks (typo)' is not on Wikipedia" in caplog.text
    assert not manifest_path(env).exists()


def test_the_real_overrides_file_is_read_by_default(
    env: Path,
    topics: Path,
    db: list[str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from narrative.overrides import OVERRIDES_FILE

    monkeypatch.setattr(cli, "OVERRIDES_FILE", OVERRIDES_FILE)
    # The fake rows don't have the real refs, so the run fails naming them.
    assert cli.run(["--topics", str(topics), "--no-resolve"]) == 1
    assert "title_overrides.csv: unknown driver ref 'brooks'" in caplog.text
