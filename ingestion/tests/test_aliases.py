import re
from pathlib import Path

import pytest

from structured.aliases import SEEDS_DIR, normalise_alias, read_seeds
from structured.errors import SeedError

# The format enforced by the alias tables' check constraint.
DB_ALIAS_FORMAT = re.compile(r"^[a-z0-9]+( [a-z0-9]+)*$")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Sergio Pérez", "sergio perez"),
        ("Kimi Räikkönen", "kimi raikkonen"),
        ("Nico Hülkenberg", "nico hulkenberg"),
        ("O'Ward", "o ward"),
        ("Heinz-Harald Frentzen", "heinz harald frentzen"),
        ("  The   Iceman ", "the iceman"),
        ("Jørgen", "jorgen"),
        ("Straße", "strasse"),
        ("Łukasz", "lukasz"),
        ("red_bull", "red bull"),
        ("brabham-alfa_romeo", "brabham alfa romeo"),
        ("Haas F1 Team", "haas f1 team"),
        ("José Froilán González", "jose froilan gonzalez"),
        ("!!!", ""),
    ],
)
def test_normalise_alias(text: str, expected: str) -> None:
    assert normalise_alias(text) == expected


@pytest.mark.parametrize("text", ["Pérez", "O'Ward", "A  B", "Ø", " x ", "ÆBC-12"])
def test_normalised_aliases_match_the_db_format(text: str) -> None:
    assert DB_ALIAS_FORMAT.match(normalise_alias(text))


# --- the real seed files ---


def test_real_seed_files_are_valid() -> None:
    seeds = read_seeds()

    assert len(seeds.driver_aliases) > 50
    assert len(seeds.constructor_aliases) > 20
    assert len(seeds.lineage) > 30
    for _, alias in seeds.driver_aliases + seeds.constructor_aliases:
        assert DB_ALIAS_FORMAT.match(alias), alias


def test_real_seeds_include_the_planned_examples() -> None:
    seeds = read_seeds()

    assert ("michael_schumacher", "schumi") in seeds.driver_aliases
    assert ("perez", "checo") in seeds.driver_aliases
    chain = {(s.predecessor, s.successor, s.season) for s in seeds.lineage}
    assert {
        ("tyrrell", "bar", 1999),
        ("bar", "honda", 2006),
        ("honda", "brawn", 2009),
        ("brawn", "mercedes", 2010),
        ("toleman", "benetton", 1986),
        ("renault", "alpine", 2021),
    } <= chain


def test_three_letter_codes_are_not_aliases() -> None:
    """Codes like PER, SAI, GAS would match ordinary words."""
    aliases = {alias for _, alias in read_seeds().driver_aliases}

    assert not {"per", "sai", "gas", "ham", "ver"} & aliases


# --- malformed seed files ---


def _seeds_dir(tmp_path: Path, **files: str) -> Path:
    defaults = {
        "driver_aliases.csv": "ref,alias\nhamilton,Lewis\n",
        "constructor_aliases.csv": "ref,alias\nmercedes,Silver Arrows\n",
        "constructor_lineage.csv": "predecessor,successor,season,note\nbrawn,mercedes,2010,Bought\n",
    }
    for name, content in {**defaults, **files}.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    return tmp_path


def test_reads_a_valid_seeds_dir(tmp_path: Path) -> None:
    seeds = read_seeds(_seeds_dir(tmp_path))

    assert seeds.driver_aliases == [("hamilton", "lewis")]
    assert seeds.lineage[0].note == "Bought"


@pytest.mark.parametrize(
    ("file", "content", "message"),
    [
        ("driver_aliases.csv", "alias,ref\nx,y\n", "header must be ref,alias"),
        ("driver_aliases.csv", "ref,alias\nHamilton!,x\n", "invalid ref"),
        ("driver_aliases.csv", "ref,alias\nhamilton,!!!\n", "is empty"),
        (
            "driver_aliases.csv",
            "ref,alias\nhamilton,Lewis\nhamilton,LEWIS\n",
            "duplicate alias",
        ),
        ("driver_aliases.csv", "ref,alias\nhamilton\n", "expected 2 columns"),
        ("driver_aliases.csv", "ref,alias\nhamilton,a,b\n", "expected 2 columns"),
        (
            "constructor_lineage.csv",
            "predecessor,successor,season,note\nbrawn,mercedes,twenty,\n",
            "not a year",
        ),
        (
            "constructor_lineage.csv",
            "predecessor,successor,season,note\nbrawn,mercedes,1949,\n",
            "out of range",
        ),
        (
            "constructor_lineage.csv",
            "predecessor,successor,season,note\nbrawn,brawn,2010,\n",
            "invalid predecessor/successor",
        ),
        (
            "constructor_lineage.csv",
            "predecessor,successor,season,note\nbrawn,mercedes,2010,\nbrawn,mercedes,2010,x\n",
            "duplicate lineage row",
        ),
    ],
)
def test_malformed_seeds_raise(
    tmp_path: Path, file: str, content: str, message: str
) -> None:
    with pytest.raises(SeedError, match=message):
        read_seeds(_seeds_dir(tmp_path, **{file: content}))


def test_missing_seed_file(tmp_path: Path) -> None:
    _seeds_dir(tmp_path)
    (tmp_path / "constructor_aliases.csv").unlink()

    with pytest.raises(
        SeedError, match="cannot read seed file constructor_aliases.csv"
    ):
        read_seeds(tmp_path)


def test_seeds_dir_is_inside_the_package() -> None:
    assert SEEDS_DIR.is_dir()
    assert SEEDS_DIR.parent.name == "structured"
