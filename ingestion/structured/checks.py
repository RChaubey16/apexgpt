"""Sanity checks for the structured F1 data: known facts, integrity rules, size.

Each check is one SQL query returning a single value, compared with an expected
value. They run:

- inside the loader's transaction, before commit: a failing check rolls the
  whole load back, so a bad dump can never replace good data;
- standalone and read-only, against any database (dev, Neon):

      uv run python -m structured.checks

A check only runs when every season it is about is loaded, so a partial load
(e.g. --first-season 2024) skips the 1950s facts instead of failing them. Facts are taken from official records; where the data's
definition differs (poles = grid 1, starts approximate) the expected values
follow the data's definition, as documented in docs/DATA-STRATEGY.md.
"""

import argparse
import logging
import operator
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import psycopg

from structured.config import Settings
from structured.errors import IngestionError

logger = logging.getLogger(__name__)

# Structured data budget (docs/DATA-STRATEGY.md: ~15-25 MB).
SIZE_BUDGET_BYTES = 25_000_000

F1_TABLES = (
    "seasons",
    "circuits",
    "drivers",
    "constructors",
    "status",
    "races",
    "results",
    "sprint_results",
    "qualifying",
    "driver_standings",
    "constructor_standings",
    "pit_stops",
    "driver_aliases",
    "constructor_aliases",
    "constructor_lineage",
)

_COMPARISONS: dict[str, tuple[str, Callable[[Any, Any], bool]]] = {
    "eq": ("=", operator.eq),
    "lt": ("<", operator.lt),
    "ge": (">=", operator.ge),
}


@dataclass(frozen=True)
class Check:
    name: str
    sql: str
    expected: Any
    # Every season in this span must be loaded for the check to apply.
    seasons: tuple[int, int] | None = None
    comparison: str = "eq"
    # Needs aliases/lineage (skipped when the loader runs with --no-seeds).
    needs_seeds: bool = False


@dataclass(frozen=True)
class CheckResult:
    check: Check
    actual: Any = None
    passed: bool = False
    skipped: bool = False

    def describe(self) -> str:
        if self.skipped:
            return f"SKIP  {self.check.name} (not applicable to the loaded data)"
        symbol = _COMPARISONS[self.check.comparison][0]
        status = "PASS" if self.passed else "FAIL"
        return f"{status}  {self.check.name}: {self.actual!r} (expected {symbol} {self.check.expected!r})"


class DataCheckError(IngestionError):
    """One or more sanity checks failed."""

    def __init__(self, failures: Sequence[CheckResult]) -> None:
        self.failures = list(failures)
        lines = "; ".join(r.describe() for r in failures)
        super().__init__(f"{len(failures)} data check(s) failed: {lines}")


def _career(driver: str, column: str) -> str:
    return f"SELECT {column} FROM v_driver_career WHERE driver_ref = '{driver}'"  # noqa: S608


def _season(season: int, column: str) -> str:
    return (
        f"SELECT {column} FROM v_season_summary WHERE season = {season}"  # noqa: S608
    )


CHECKS: tuple[Check, ...] = (
    # --- the plan's headline facts ---
    Check("Hamilton has 105 wins", _career("hamilton", "wins"), 105, (2007, 2025)),
    Check("2021 champion is Verstappen", _season(2021, "champion_ref"), "max_verstappen", (2021, 2021)),
    Check("1950 had 7 championship races", "SELECT count(*) FROM races WHERE season = 1950", 7, (1950, 1950)),
    # --- careers (official figures; poles = grid 1) ---
    Check("Hamilton has 7 titles", _career("hamilton", "championships"), 7, (2007, 2025)),
    Check("Hamilton has 104 poles", _career("hamilton", "poles"), 104, (2007, 2025)),
    Check("Hamilton has 202 podiums", _career("hamilton", "podiums"), 202, (2007, 2025)),
    Check("Michael Schumacher has 91 wins", _career("michael_schumacher", "wins"), 91, (1991, 2012)),
    Check("Michael Schumacher has 7 titles", _career("michael_schumacher", "championships"), 7, (1991, 2012)),
    Check("Michael Schumacher scored 1566 points", _career("michael_schumacher", "total_points"), Decimal("1566"), (1991, 2012)),
    Check("Senna has 65 poles", _career("senna", "poles"), 65, (1984, 1994)),
    Check("Senna has 41 wins", _career("senna", "wins"), 41, (1984, 1994)),
    Check("Prost has 51 wins", _career("prost", "wins"), 51, (1980, 1993)),
    Check("Fangio has 5 titles", _career("fangio", "championships"), 5, (1950, 1958)),
    # --- seasons ---
    Check("1950 champion is Farina", _season(1950, "champion_ref"), "farina", (1950, 1950)),
    Check("2008 title margin is 1 point", _season(2008, "title_margin"), Decimal("1"), (2008, 2008)),
    Check("2021 champion scored 395.5", _season(2021, "champion_points"), Decimal("395.5"), (2021, 2021)),
    Check("2025 champion is Norris", _season(2025, "champion_ref"), "norris", (2025, 2025)),
    Check("First constructors' champion is Vanwall (1958)", _season(1958, "constructors_champion_ref"), "vanwall", (1958, 1958)),
    Check("2024 constructors' champion is McLaren", _season(2024, "constructors_champion_ref"), "mclaren", (2024, 2024)),
    Check("1950-2025 has 1149 races", "SELECT count(*) FROM races WHERE season BETWEEN 1950 AND 2025", 1149, (1950, 2025)),
    Check("2025 had 24 races", "SELECT count(*) FROM races WHERE season = 2025", 24, (2025, 2025)),
    Check(
        "Senna out-qualified Prost 14-2 in 1988",
        "SELECT qualified_ahead || '-' || qualified_behind FROM v_head_to_head_teammates "
        "WHERE season = 1988 AND driver_ref = 'senna' AND teammate_ref = 'prost'",
        "14-2",
        (1988, 1988),
    ),
    # --- integrity (must hold for any range) ---
    Check(
        "Every race has results",
        "SELECT count(*) FROM races ra WHERE NOT EXISTS "
        "(SELECT 1 FROM results r WHERE r.race_id = ra.race_id)",
        0,
    ),
    Check(
        "Every race has a winner",
        "SELECT count(*) FROM races ra WHERE NOT EXISTS "
        "(SELECT 1 FROM results r WHERE r.race_id = ra.race_id AND r.position = 1)",
        0,
    ),
    Check(
        "Every race has driver standings",
        "SELECT count(*) FROM races ra WHERE NOT EXISTS "
        "(SELECT 1 FROM driver_standings ds WHERE ds.race_id = ra.race_id)",
        0,
    ),
    Check(
        "Round numbers run 1..n in every season",
        "SELECT count(*) FROM (SELECT season FROM races GROUP BY season "
        "HAVING max(round) <> count(*) OR min(round) <> 1) bad",
        0,
    ),
    Check("Every season has a champion", "SELECT count(*) FROM v_season_summary WHERE champion_ref IS NULL", 0),
    Check(
        "Every season from 1958 has a constructors' champion",
        "SELECT count(*) FROM v_season_summary WHERE season >= 1958 "
        "AND constructors_champion_ref IS NULL",
        0,
    ),
    Check(
        "Every driver has an alias",
        "SELECT count(*) FROM drivers d WHERE NOT EXISTS "
        "(SELECT 1 FROM driver_aliases a WHERE a.driver_id = d.driver_id)",
        0,
        needs_seeds=True,
    ),
    # --- size budget ---
    Check(
        f"Structured data is under {SIZE_BUDGET_BYTES // 1_000_000} MB",
        "SELECT sum(pg_total_relation_size(c.oid)) FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relname IN ("
        "'seasons', 'circuits', 'drivers', 'constructors', 'status', 'races', "
        "'results', 'sprint_results', 'qualifying', 'driver_standings', "
        "'constructor_standings', 'pit_stops', 'driver_aliases', "
        "'constructor_aliases', 'constructor_lineage')",  # all of F1_TABLES (tested)
        SIZE_BUDGET_BYTES,
        comparison="lt",
    ),
)  # fmt: skip


def loaded_seasons(cur: psycopg.Cursor) -> set[int]:
    cur.execute("SELECT DISTINCT season FROM races")
    return {season for (season,) in cur.fetchall()}


def _applies(check: Check, seasons: set[int], seeds_synced: bool) -> bool:
    if check.needs_seeds and not seeds_synced:
        return False
    if check.seasons is None:
        return True
    first, last = check.seasons
    return set(range(first, last + 1)) <= seasons


def run_checks(
    cur: psycopg.Cursor,
    checks: Sequence[Check] = CHECKS,
    seeds_synced: bool = True,
) -> list[CheckResult]:
    """Run the checks that apply to the data in the database (or transaction)."""
    seasons = loaded_seasons(cur)
    results = []
    for check in checks:
        if not _applies(check, seasons, seeds_synced):
            results.append(CheckResult(check, skipped=True))
            continue
        cur.execute(check.sql)
        row = cur.fetchone()
        actual = row[0] if row else None
        compare = _COMPARISONS[check.comparison][1]
        passed = actual is not None and compare(actual, check.expected)
        results.append(CheckResult(check, actual=actual, passed=passed))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m structured.checks",
        description="Run the structured-data sanity checks (read-only).",
    )
    parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = Settings()
    if settings.database_url is None:
        logger.error("DATABASE_URL is not set (see .env.example)")
        return 2
    try:
        with psycopg.connect(
            settings.database_url.get_secret_value(),
            connect_timeout=settings.database_connect_timeout,
            prepare_threshold=None,
        ) as conn:
            conn.read_only = True
            with conn.cursor() as cur:
                if not loaded_seasons(cur):
                    logger.error("No races loaded: run `python -m structured` first")
                    return 1
                results = run_checks(cur, CHECKS)
    except psycopg.Error as exc:
        logger.error("Checks could not run: %s", type(exc).__name__)
        return 1

    for result in results:
        print(result.describe())
    failed = [r for r in results if not r.passed and not r.skipped]
    ran = sum(not r.skipped for r in results)
    print(f"\n{ran - len(failed)}/{ran} passed, {len(results) - ran} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
