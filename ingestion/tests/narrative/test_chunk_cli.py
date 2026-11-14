import logging
from pathlib import Path

import pytest

from narrative import chunk as cli
from narrative.articles import (
    ArticleRecord,
    SectionRecord,
    articles_path,
    write_articles,
)
from narrative.chunker import ChunkError
from narrative.chunks import ChunkRecord, chunk_article, chunks_path, read_chunks
from narrative.config import WikiSettings
from narrative.errors import SelectionError
from narrative.selection import Depth, Kind

RACE = ArticleRecord(
    title="1989 Japanese Grand Prix",
    pageid=1,
    revid=11,
    url="https://en.wikipedia.org/wiki/1989_Japanese_Grand_Prix",
    depth=Depth.RACE,
    kinds=(Kind.RACE, Kind.TOPIC),
    season=1989,
    race_id=483,
    circuit_id=53,
    driver_ids=(613, 652),
    topic="iconic_race",
    sections=(
        SectionRecord(path=(), text="The 1989 Japanese Grand Prix was at Suzuka."),
        SectionRecord(path=("Race",), text="Senna and Prost collided at the chicane."),
    ),
)
DRIVER = ArticleRecord(
    title="Carl Forberg",
    pageid=2,
    revid=22,
    url="https://en.wikipedia.org/wiki/Carl_Forberg",
    depth=Depth.LEAD,
    kinds=(Kind.DRIVER,),
    driver_ids=(9,),
    sections=(SectionRecord(path=(), text="Carl Forberg was a driver."),),
)


@pytest.fixture
def data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A DATA_DIR with cleaned articles."""
    monkeypatch.setitem(WikiSettings.model_config, "env_file", None)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    write_articles(articles_path(tmp_path), [RACE, DRIVER])
    return tmp_path


def test_chunks_the_articles_with_their_metadata(
    data: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)

    assert cli.run([]) == 0

    lead, race, driver = list(read_chunks(chunks_path(data)))
    assert race == ChunkRecord(
        pageid=1,
        index=1,
        title="1989 Japanese Grand Prix",
        revid=11,
        source_url="https://en.wikipedia.org/wiki/1989_Japanese_Grand_Prix",
        section=("Race",),
        text="Senna and Prost collided at the chicane.",
        tokens=race.tokens,
        depth=Depth.RACE,
        kinds=(Kind.RACE, Kind.TOPIC),
        season=1989,
        race_id=483,
        circuit_id=53,
        driver_ids=(613, 652),
        topic="iconic_race",
    )
    assert (lead.index, lead.section) == (0, ())
    assert race.heading == "1989 Japanese Grand Prix > Race"
    assert race.embedding_text == (
        "1989 Japanese Grand Prix > Race\n\nSenna and Prost collided at the chicane."
    )
    assert (driver.pageid, driver.index, driver.driver_ids) == (2, 0, (9,))
    assert driver.heading == "Carl Forberg"
    assert "Chunked 2 articles into 3 chunks" in caplog.text
    assert "3 under 100" in caplog.text


def test_show_prints_one_article_and_writes_nothing(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.run(["--show", "Carl Forberg"]) == 0

    out = capsys.readouterr().out
    assert "## [0] Carl Forberg (~" in out
    assert "Carl Forberg was a driver." in out
    assert "Japanese" not in out
    assert not chunks_path(data).exists()


def test_show_unknown_title(data: Path, caplog: pytest.LogCaptureFixture) -> None:
    assert cli.run(["--show", "Nobody"]) == 1
    assert "'Nobody' is not in the cleaned articles" in caplog.text


def test_invalid_show_title_is_a_usage_error(data: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.run(["--show", "a|b"])
    assert exc.value.code == 2


def test_missing_articles_file(data: Path, caplog: pytest.LogCaptureFixture) -> None:
    articles_path(data).unlink()

    assert cli.run([]) == 1
    assert "run `python -m narrative.clean` first" in caplog.text


def test_an_article_that_cannot_be_chunked_writes_nothing(
    data: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = chunks_path(data)
    output.write_text("previous\n")

    def failing(article: ArticleRecord) -> list[ChunkRecord]:
        if article.pageid == 2:
            raise ChunkError(f"{article.title!r}: broken")
        return chunk_article(article)

    monkeypatch.setattr(cli, "chunk_article", failing)

    assert cli.run([]) == 1
    assert "1 articles could not be chunked (nothing written)" in caplog.text
    assert "'Carl Forberg': broken" in caplog.text
    assert output.read_text() == "previous\n"


def test_invalid_setting(monkeypatch: pytest.MonkeyPatch, data: Path) -> None:
    monkeypatch.setenv("WIKI_MIN_INTERVAL_SECONDS", "0")
    assert cli.run([]) == 2


def test_read_chunks_rejects_a_bad_line(data: Path) -> None:
    assert cli.run([]) == 0
    path = chunks_path(data)
    with path.open("a") as f:
        f.write('{"pageid": 3}\n')

    with pytest.raises(SelectionError, match="line 4 is unreadable"):
        list(read_chunks(path))


def test_read_chunks_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SelectionError, match="run `python -m narrative.chunk` first"):
        list(read_chunks(chunks_path(tmp_path)))


def test_chunk_indexes_count_up_within_an_article() -> None:
    long = ArticleRecord.model_validate(
        RACE.model_dump()
        | {
            "sections": [
                {"path": (), "text": "Lead."},
                {"path": ("Race",), "text": " ".join(["Senna passed Prost."] * 300)},
            ]
        }
    )

    chunks = chunk_article(long)
    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert len(chunks) >= 3
    assert all(c.race_id == 483 for c in chunks)
