from pathlib import Path

import pytest

from structured import dump
from structured.dump import DumpReader
from structured.errors import DumpError
from structured.transform import transform
from tests.fixture_dump import tables, write_zip


def test_reads_tables_from_zip(tmp_path: Path) -> None:
    with DumpReader(write_zip(tmp_path / "dump.zip")) as reader:
        seasons = list(reader.rows("season"))

    assert [s["year"] for s in seasons] == ["2020", "2021", "2027"]


def test_full_transform_from_zip(tmp_path: Path) -> None:
    with DumpReader(write_zip(tmp_path / "dump.zip")) as reader:
        data = transform(reader)

    assert data.counts()["results"] == 5


def test_missing_table(tmp_path: Path) -> None:
    data = tables()
    del data["pitstop"]

    with DumpReader(write_zip(tmp_path / "dump.zip", data)) as reader, pytest.raises(
        DumpError, match="no formula_one_pitstop.csv"
    ):
        list(reader.rows("pitstop"))


def test_missing_column(tmp_path: Path) -> None:
    data = tables()
    for row in data["round"]:
        del row["circuit_id"]

    with DumpReader(write_zip(tmp_path / "dump.zip", data)) as reader, pytest.raises(
        DumpError, match="'round' is missing columns: circuit_id"
    ):
        list(reader.rows("round"))


def test_not_a_zip(tmp_path: Path) -> None:
    path = tmp_path / "dump.zip"
    path.write_text("not a zip")

    with pytest.raises(DumpError, match="not a readable zip"):
        DumpReader(path)


def test_oversized_member_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dump, "MAX_MEMBER_BYTES", 10)

    with DumpReader(write_zip(tmp_path / "dump.zip")) as reader, pytest.raises(
        DumpError, match="unexpectedly large"
    ):
        list(reader.rows("season"))
