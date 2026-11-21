import pytest

from app.retrieval.filters import (
    LAST_SEASON,
    MAX_SEASONS,
    NO_FILTERS,
    SearchFilters,
    filters_from_query,
)


@pytest.mark.parametrize(
    ("query", "seasons"),
    [
        ("How did Hunt beat Lauda in 1976", (1976,)),
        ("Explain Abu Dhabi 2021.", (2021,)),
        ("1950 British Grand Prix", (1950,)),
        ("2025 champion?", (2025,)),
        ("Senna in 1988, 1989 and 1990", (1988, 1989, 1990)),
        ("1990 vs 1989 vs 1990", (1989, 1990)),  # de-duplicated and sorted
        ("the 1984's Monaco race", (1984,)),  # possessive still names a year
        ("(1994)", (1994,)),
    ],
)
def test_years_become_season_filters(query: str, seasons: tuple[int, ...]) -> None:
    assert filters_from_query(query).seasons == seasons


@pytest.mark.parametrize(
    "query",
    [
        "Senna Prost Suzuka collision",  # no year
        "dominance in the 1980s",  # a decade, not a season
        "2026 regulations",  # after the corpus: ignored, not an empty filter
        "1949 Grand Prix season",  # before the World Championship
        "he scored 19760 points",  # part of a longer number
        "pole in 1:19.760",
        "a 1.1990 ratio",
        "costs 2,1990",
    ],
)
def test_no_season_filter(query: str) -> None:
    assert filters_from_query(query) == NO_FILTERS


def test_too_many_years_mean_no_filter() -> None:
    years = " ".join(str(1990 + i) for i in range(MAX_SEASONS + 1))
    assert filters_from_query(f"champions {years}") == NO_FILTERS


def test_filters_are_normalised() -> None:
    assert SearchFilters(seasons=(1990, 1989, 1990)).seasons == (1989, 1990)


@pytest.mark.parametrize(
    ("seasons", "message"),
    [
        ((1949,), "outside"),
        ((LAST_SEASON + 1,), "outside"),
        (tuple(range(1990, 1990 + MAX_SEASONS + 1)), "at most"),
        (("1990",), "integers"),
        ((True,), "integers"),
    ],
)
def test_invalid_filters_are_rejected(
    seasons: tuple[object, ...], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        SearchFilters(seasons=seasons)  # type: ignore[arg-type]
