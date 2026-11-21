"""Metadata filters for knowledge search, and extracting them from the question.

Only race chunks are tagged with a season; driver, constructor, circuit and most
topic chunks are not (see the `chunks` metadata). So a season filter keeps the
chunks of those seasons **and the chunks with no season**: "How did Hunt beat
Lauda in 1976" drops other years' race reports but keeps the Hunt–Lauda rivalry
and the drivers' biographies.

Names → driver/constructor/circuit IDs is entity resolution (F3.4), not here.
"""

import re
from dataclasses import dataclass

FIRST_SEASON = 1950
# The corpus ends with the 2025 season; 2026+ is out of scope for ApexGPT.
LAST_SEASON = 2025
# More years than this is a range question ("since 1990"), not a filter.
MAX_SEASONS = 10

# A standalone four-digit year. Not part of a longer number, and not a decade
# ("the 1980s"), which would wrongly narrow the search to a single season.
_YEAR = re.compile(r"(?<![\d.,])(19[5-9]\d|20[0-2]\d)(?![\d.,]?\d)(?!s\b)")


@dataclass(frozen=True)
class SearchFilters:
    """seasons: keep chunks of these seasons and chunks with no season."""

    seasons: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        seasons = tuple(sorted(set(self.seasons)))
        if len(seasons) > MAX_SEASONS:
            raise ValueError(f"at most {MAX_SEASONS} seasons can be filtered on")
        for season in seasons:
            if isinstance(season, bool) or not isinstance(season, int):
                raise ValueError("seasons must be integers")
            if not FIRST_SEASON <= season <= LAST_SEASON:
                raise ValueError(
                    f"season {season} is outside {FIRST_SEASON}–{LAST_SEASON}"
                )
        object.__setattr__(self, "seasons", seasons)


NO_FILTERS = SearchFilters()


def filters_from_query(query: str) -> SearchFilters:
    """Season filter from the years named in the question (1950–2025).

    Years outside the corpus (e.g. 2026) are ignored rather than filtered on,
    which would leave only untagged chunks. Too many years means no filter.
    """
    years = {
        int(match)
        for match in _YEAR.findall(query)
        if FIRST_SEASON <= int(match) <= LAST_SEASON
    }
    if not years or len(years) > MAX_SEASONS:
        return NO_FILTERS
    return SearchFilters(seasons=tuple(years))
