import json
import logging
from pathlib import Path

import pytest

from narrative import clean as cli
from narrative.articles import (
    ArticleRecord,
    SectionRecord,
    articles_path,
    read_articles,
    write_articles,
)
from narrative.cache import ArticleCache
from narrative.config import WikiSettings
from narrative.errors import SelectionError
from narrative.manifest import manifest_path, write_manifest
from narrative.selection import Depth, Kind, Selected
from narrative.wiki import Article

RACE_HTML = (
    '<div class="mw-parser-output"><p>The 1989 Japanese Grand Prix was at Suzuka.'
    '<sup class="reference">[1]</sup></p>'
    '<div class="mw-heading mw-heading2"><h2 id="Qualifying">Qualifying</h2></div>'
    "<p>Senna took pole.</p>"
    '<div class="mw-heading mw-heading2"><h2 id="Race">Race</h2></div>'
    "<p>Senna and Prost collided at the chicane.</p>"
    '<div class="mw-heading mw-heading2"><h2 id="References">References</h2></div>'
    "<p>A source.</p></div>"
)
DRIVER_HTML = '<div class="mw-parser-output"><p>Carl Forberg was a driver.</p></div>'

SELECTED = [
    Selected(
        title="1989 Japanese Grand Prix",
        kinds=(Kind.RACE, Kind.TOPIC),
        depth=Depth.RACE,
        season=1989,
        race_id=483,
        circuit_id=53,
        driver_ids=(613, 652),
        topic="iconic_race",
        pageid=1,
    ),
    Selected(
        title="Carl Forberg",
        kinds=(Kind.DRIVER,),
        depth=Depth.LEAD,
        driver_ids=(9,),
        pageid=2,
    ),
]


@pytest.fixture
def data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A DATA_DIR with a selection and its fetched articles."""
    monkeypatch.setitem(WikiSettings.model_config, "env_file", None)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    write_manifest(manifest_path(tmp_path), SELECTED)
    cache = ArticleCache(tmp_path / "wikipedia")
    cache.put(
        Article(
            "1989 Japanese Grand Prix", "1989 Japanese Grand Prix", 1, 11, RACE_HTML
        )
    )
    cache.put(Article("Carl Forberg", "Carl Forberg", 2, 22, DRIVER_HTML))
    return tmp_path


def test_cleans_the_selection_into_articles_jsonl(
    data: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)

    assert cli.run([]) == 0

    race, driver = list(read_articles(articles_path(data)))
    assert race.title == "1989 Japanese Grand Prix"
    assert (race.pageid, race.revid) == (1, 11)
    assert race.url == "https://en.wikipedia.org/wiki/1989_Japanese_Grand_Prix"
    assert (race.depth, race.kinds, race.topic) == (
        Depth.RACE,
        (Kind.RACE, Kind.TOPIC),
        "iconic_race",
    )
    assert (race.season, race.race_id, race.circuit_id, race.driver_ids) == (
        1989,
        483,
        53,
        (613, 652),
    )
    assert race.sections == (
        SectionRecord(path=(), text="The 1989 Japanese Grand Prix was at Suzuka."),
        SectionRecord(path=("Race",), text="Senna and Prost collided at the chicane."),
    )
    assert driver.sections[0].text == "Carl Forberg was a driver."
    assert "Cleaned 2 articles: 20 words" in caplog.text
    assert "2 articles kept under 20 words" in caplog.text
    assert "'Carl Forberg' (5 words)" in caplog.text


def test_missing_or_stale_articles_fail_and_keep_the_previous_file(
    data: Path, caplog: pytest.LogCaptureFixture
) -> None:
    assert cli.run([]) == 0
    before = articles_path(data).read_text()
    cache = ArticleCache(data / "wikipedia")
    cache.path_for("Carl Forberg").unlink()
    cache.put(
        Article(
            "1989 Japanese Grand Prix", "1989 Japanese Grand Prix", 99, 11, RACE_HTML
        )
    )

    assert cli.run([]) == 1

    assert "'Carl Forberg' is not fetched yet" in caplog.text
    assert "the cached page (99) isn't the selected one (1)" in caplog.text
    assert "nothing written" in caplog.text
    assert articles_path(data).read_text() == before


def test_unusable_html_is_reported(
    data: Path, caplog: pytest.LogCaptureFixture
) -> None:
    ArticleCache(data / "wikipedia").put(
        Article("Carl Forberg", "Carl Forberg", 2, 22, "  ")
    )
    assert cli.run([]) == 1
    assert "'Carl Forberg': article HTML is empty" in caplog.text
    assert not articles_path(data).exists()


def test_without_a_selection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setitem(WikiSettings.model_config, "env_file", None)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert cli.run([]) == 1
    assert "run `python -m narrative.select` first" in caplog.text


def test_show_prints_one_article_and_writes_nothing(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.run(["--show", "1989_Japanese_Grand_Prix"]) == 0

    out = capsys.readouterr().out
    assert out.startswith("1989 Japanese Grand Prix [race] 15 words")
    assert "## (lead)" in out
    assert "## Race\n\nSenna and Prost collided at the chicane." in out
    assert "Qualifying" not in out
    assert not articles_path(data).exists()


def test_show_errors(data: Path, caplog: pytest.LogCaptureFixture) -> None:
    assert cli.run(["--show", "Not Selected"]) == 1
    assert "'Not Selected' is not in the selection" in caplog.text

    ArticleCache(data / "wikipedia").path_for("Carl Forberg").unlink()
    assert cli.run(["--show", "Carl Forberg"]) == 1
    assert "not fetched yet" in caplog.text

    with pytest.raises(SystemExit):
        cli.run(["--show", "A|B"])


def test_invalid_settings(data: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WIKI_MIN_INTERVAL_SECONDS", "0")
    assert cli.run([]) == 2


def test_unwritable_output(
    data: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(path: Path, records: object) -> int:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(cli, "write_articles", boom)
    assert cli.run([]) == 1
    assert "Cannot write" in caplog.text


# --- articles.jsonl ---

RECORD = ArticleRecord(
    title="A",
    pageid=1,
    revid=2,
    url="https://en.wikipedia.org/wiki/A",
    depth=Depth.LEAD,
    kinds=(Kind.DRIVER,),
    driver_ids=(3,),
    sections=(SectionRecord(path=(), text="Text."),),
)


def test_articles_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "a.jsonl"
    assert write_articles(path, [RECORD, RECORD.model_copy(update={"title": "B"})]) == 2
    assert [r.title for r in read_articles(path)] == ["A", "B"]
    assert '"season"' not in path.read_text()  # defaults left out


def test_failed_write_keeps_the_previous_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "a.jsonl"
    write_articles(path, [RECORD])

    def records():
        yield RECORD
        raise RuntimeError("interrupted")

    with pytest.raises(RuntimeError):
        write_articles(path, records())
    assert [r.title for r in read_articles(path)] == ["A"]
    assert not list(tmp_path.glob(".tmp-*"))


@pytest.mark.parametrize(
    "line",
    [
        "not json",
        json.dumps({"title": "A"}),
        json.dumps({**json.loads(RECORD.model_dump_json()), "depth": "most"}),
        json.dumps(
            {
                **json.loads(RECORD.model_dump_json()),
                "sections": [{"path": [], "text": ""}],
            }
        ),
        json.dumps({**json.loads(RECORD.model_dump_json()), "extra": 1}),
    ],
)
def test_bad_lines_are_refused(tmp_path: Path, line: str) -> None:
    path = tmp_path / "a.jsonl"
    path.write_text(RECORD.model_dump_json() + "\n" + line + "\n")
    with pytest.raises(SelectionError, match="line 2 is unreadable"):
        list(read_articles(path))


def test_missing_articles_file(tmp_path: Path) -> None:
    with pytest.raises(SelectionError, match="run `python -m narrative.clean` first"):
        list(read_articles(tmp_path / "nope.jsonl"))


def test_leftover_markup_is_reported(
    data: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # Markup the cleaner doesn't know: CSS inside a paragraph, a bare citation marker.
    html = '<div class="mw-parser-output"><p>Text .mw-parser-output .x{color:red} [12] here.</p></div>'
    ArticleCache(data / "wikipedia").put(
        Article("Carl Forberg", "Carl Forberg", 2, 22, html)
    )

    assert cli.run([]) == 0  # reported, not fatal
    assert "1 sections still contain markup" in caplog.text
    assert "'Carl Forberg' [lead]" in caplog.text
