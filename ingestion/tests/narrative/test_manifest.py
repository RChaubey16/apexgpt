import json
from pathlib import Path

import pytest

from narrative.errors import SelectionError
from narrative.manifest import manifest_path, read_manifest, write_manifest
from narrative.selection import Depth, Kind, Selected

ARTICLES = [
    Selected(
        title="1989 Japanese Grand Prix",
        kinds=(Kind.RACE, Kind.TOPIC),
        depth=Depth.FULL,
        season=1989,
        race_id=480,
        circuit_id=22,
        driver_ids=(102, 117),
        topic="iconic_race",
        pageid=1,
    ),
    Selected(
        title="Las Vegas Grand Prix",
        kinds=(Kind.CIRCUIT,),
        depth=Depth.CIRCUIT,
        circuit_id=80,
        anchor="Circuit",
        pageid=2,
    ),
]


def test_round_trip(tmp_path: Path) -> None:
    path = manifest_path(tmp_path)

    written = write_manifest(path, ARTICLES)
    read = read_manifest(path)

    assert path == tmp_path / "narrative" / "selection.json"
    assert read.articles == tuple(ARTICLES)
    assert read.counts == written.counts
    assert read.counts["depth"]["full"] == 1
    assert not list(path.parent.glob(".tmp-*"))
    # Defaults are left out to keep the file small.
    raw = json.loads(path.read_text())
    assert "race_id" not in raw["articles"][1]


def test_refuses_unresolved_articles(tmp_path: Path) -> None:
    unresolved = ARTICLES[0].model_copy(update={"pageid": None})
    with pytest.raises(SelectionError, match="unresolved"):
        write_manifest(tmp_path / "s.json", [unresolved])
    assert not (tmp_path / "s.json").exists()


def test_failed_write_keeps_the_previous_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "s.json"
    write_manifest(path, ARTICLES[:1])

    def boom(*args: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("narrative.manifest.os.replace", boom)
    with pytest.raises(OSError):
        write_manifest(path, ARTICLES)

    assert len(read_manifest(path).articles) == 1
    assert not list(tmp_path.glob(".tmp-*"))


def test_missing_manifest(tmp_path: Path) -> None:
    with pytest.raises(SelectionError, match="run `python -m narrative.select` first"):
        read_manifest(tmp_path / "nope.json")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: "not json",
        lambda d: {**d, "version": 99},
        lambda d: {**d, "extra": 1},
        lambda d: {**d, "articles": [{**d["articles"][0], "depth": "most"}]},
        lambda d: {**d, "articles": [{**d["articles"][0], "kinds": ["gossip"]}]},
        lambda d: {**d, "articles": [d["articles"][0], d["articles"][0]]},
        lambda d: {
            **d,
            "articles": [{k: v for k, v in d["articles"][0].items() if k != "pageid"}],
        },
    ],
)
def test_bad_manifests_are_refused(tmp_path: Path, mutate) -> None:
    path = tmp_path / "s.json"
    write_manifest(path, ARTICLES)
    data = mutate(json.loads(path.read_text()))
    path.write_text(data if isinstance(data, str) else json.dumps(data))

    with pytest.raises(SelectionError, match="python -m narrative.select"):
        read_manifest(path)


def test_oversized_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "s.json"
    write_manifest(path, ARTICLES)
    monkeypatch.setattr("narrative.manifest.MAX_MANIFEST_BYTES", 10)
    with pytest.raises(SelectionError, match="unexpectedly large"):
        read_manifest(path)
