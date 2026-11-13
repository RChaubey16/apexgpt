from decimal import Decimal

import pytest

from structured.checks import (
    CHECKS,
    F1_TABLES,
    Check,
    CheckResult,
    DataCheckError,
    _applies,
)

CHECK = Check("Example", "SELECT 1", 1, seasons=(2020, 2021))


@pytest.mark.parametrize(
    ("seasons", "expected"),
    [
        ({2020, 2021}, True),
        ({2019, 2020, 2021, 2022}, True),
        ({2021}, False),  # 2020 missing
        (set(), False),
    ],
)
def test_check_applies_only_when_all_its_seasons_are_loaded(
    seasons: set[int], expected: bool
) -> None:
    assert _applies(CHECK, seasons, seeds_synced=True) is expected


def test_checks_without_seasons_always_apply() -> None:
    assert _applies(Check("Any", "SELECT 0", 0), set(), seeds_synced=True)


def test_seed_checks_are_skipped_without_seeds() -> None:
    check = Check("Aliases", "SELECT 0", 0, needs_seeds=True)

    assert _applies(check, set(), seeds_synced=True)
    assert not _applies(check, set(), seeds_synced=False)


def test_describe() -> None:
    assert CheckResult(CHECK, actual=1, passed=True).describe() == (
        "PASS  Example: 1 (expected = 1)"
    )
    assert CheckResult(CHECK, actual=2).describe() == "FAIL  Example: 2 (expected = 1)"
    assert CheckResult(CHECK, skipped=True).describe().startswith("SKIP  Example")
    size = Check("Size", "SELECT 1", 10, comparison="lt")
    assert "(expected < 10)" in CheckResult(size, actual=5, passed=True).describe()


def test_data_check_error_lists_failures() -> None:
    error = DataCheckError([CheckResult(CHECK, actual=2)])

    assert "1 data check(s) failed" in str(error)
    assert "FAIL  Example: 2" in str(error)


# --- the real check list ---


def test_check_names_are_unique() -> None:
    names = [c.name for c in CHECKS]

    assert len(names) == len(set(names))


def test_plan_headline_checks_are_present() -> None:
    by_name = {c.name: c for c in CHECKS}

    assert by_name["Hamilton has 105 wins"].expected == 105
    assert by_name["2021 champion is Verstappen"].expected == "max_verstappen"
    assert by_name["1950 had 7 championship races"].expected == 7
    size = next(c for c in CHECKS if c.name.startswith("Structured data is under"))
    assert (size.comparison, size.expected) == ("lt", 25_000_000)


def test_size_check_covers_every_f1_table() -> None:
    size = next(c for c in CHECKS if c.name.startswith("Structured data is under"))

    for table in F1_TABLES:
        assert f"'{table}'" in size.sql


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.name)
def test_check_definitions_are_valid(check: Check) -> None:
    assert check.comparison in {"eq", "lt", "ge"}
    assert check.sql.lstrip().upper().startswith("SELECT")
    if check.seasons:
        first, last = check.seasons
        assert 1950 <= first <= last <= 2025
    assert not isinstance(check.expected, float), "use Decimal for points"
    if "points" in check.name or "margin" in check.name:
        assert isinstance(check.expected, Decimal)
