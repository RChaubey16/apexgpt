from pathlib import Path

import pytest

from narrative.errors import SelectionError
from narrative.overrides import OVERRIDES_FILE, parse_overrides, read_overrides
from narrative.selection import Kind, TitleOverride


def test_parse_overrides() -> None:
    text = (
        "# stale URLs\n"
        "kind,ref,title\n"
        "driver,brooks,Tony_Brooks (racing driver)\n"
        "\n"
        "  # indented comment\n"
        "constructor,jaguar, Jaguar Racing (Formula One) \n"
        "circuit,vegas,Las Vegas Strip Circuit\n"
    )

    assert parse_overrides(text) == [
        TitleOverride(Kind.DRIVER, "brooks", "Tony Brooks (racing driver)"),
        TitleOverride(Kind.CONSTRUCTOR, "jaguar", "Jaguar Racing (Formula One)"),
        TitleOverride(Kind.CIRCUIT, "vegas", "Las Vegas Strip Circuit"),
    ]


def test_header_only_is_empty() -> None:
    assert parse_overrides("kind,ref,title\n") == []


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("", "the header must be kind,ref,title"),
        ("ref,kind,title\n", "the header must be"),
        ("kind,ref,title,note\n", "the header must be"),
        (
            "kind,ref,title\nrace,1,X\n",
            "row 2: kind must be one of driver, constructor, circuit",
        ),
        ("kind,ref,title\ndriver,,X\n", "row 2: ref is empty"),
        ("kind,ref,title\ndriver,brooks,\n", "row 2: title is empty"),
        ("kind,ref,title\ndriver,brooks,A|B\n", "row 2: title contains"),
        ("kind,ref,title\ndriver,brooks\n", "row 2: expected 3 columns"),
        ("kind,ref,title\ndriver,brooks,A,B\n", "row 2: expected 3 columns"),
        (
            "kind,ref,title\ndriver,brooks,A\ndriver,brooks,B\n",
            "row 3: driver 'brooks' is listed twice",
        ),
        ('kind,ref,title\ndriver,brooks,"unclosed\n', "not valid CSV"),
    ],
)
def test_invalid_overrides(text: str, problem: str) -> None:
    with pytest.raises(SelectionError) as exc:
        parse_overrides(text)
    assert problem in str(exc.value)


def test_same_ref_for_different_kinds_is_fine() -> None:
    text = "kind,ref,title\ndriver,brabham,A\nconstructor,brabham,B\n"
    assert len(parse_overrides(text)) == 2


def test_read_overrides_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SelectionError, match="cannot read"):
        read_overrides(tmp_path / "missing.csv")

    monkeypatch.setattr("narrative.overrides.MAX_FILE_BYTES", 5)
    big = tmp_path / "big.csv"
    big.write_text("kind,ref,title\n")
    with pytest.raises(SelectionError, match="unexpectedly large"):
        read_overrides(big)


def test_the_real_overrides_file_is_valid() -> None:
    overrides = read_overrides(OVERRIDES_FILE)

    by_ref = {(o.kind, o.ref): o.title for o in overrides}
    assert by_ref[(Kind.DRIVER, "brooks")] == "Tony Brooks (racing driver)"
    assert by_ref[(Kind.CONSTRUCTOR, "jaguar")] == "Jaguar Racing (Formula One)"
    assert len(overrides) >= 25
