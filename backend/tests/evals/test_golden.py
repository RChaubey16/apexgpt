"""The golden set file, its schema and answer matching (F6.1). No database needed;
tests/corpus/test_golden_set.py checks the expectations against the real data."""

from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from evals.golden import (
    DEFAULT_PATH,
    Behavior,
    Category,
    GoldenSetError,
    cell_text,
    contains_value,
    load_golden_set,
    missing_values,
    normalise,
    parse_golden_set,
)

# --- the real file -----------------------------------------------------------

GOLDEN = load_golden_set()

MINIMUM_PER_CATEGORY = {
    Category.STATS: 15,
    Category.SEASONS: 10,
    Category.RACES: 8,
    Category.CRASHES: 8,
    Category.RIVALRIES: 8,
    Category.MULTI_HOP: 8,
    Category.FOLLOW_UP: 6,
    Category.TRICK: 6,
    Category.OUT_OF_SCOPE: 5,
}


def test_the_file_is_at_the_repository_root() -> None:
    assert DEFAULT_PATH.parts[-2:] == ("eval", "golden.yaml")
    assert DEFAULT_PATH.is_file()


def test_about_a_hundred_questions() -> None:
    assert 90 <= len(GOLDEN.questions) <= 120


@pytest.mark.parametrize("category", list(Category), ids=str)
def test_every_category_is_covered(category: Category) -> None:
    assert len(GOLDEN.by_category()[category]) >= MINIMUM_PER_CATEGORY[category]


def test_both_tools_are_exercised_alone_and_together() -> None:
    tool_sets = {q.expect.tools for q in GOLDEN.questions}
    assert ("query_stats",) in tool_sets
    assert ("search_f1_knowledge",) in tool_sets
    assert any(set(t) == {"query_stats", "search_f1_knowledge"} for t in tool_sets)


@pytest.mark.parametrize(
    "question_id",
    [
        # Known Issues the golden set must keep tracking (docs/PROGRESS.md).
        "races-abu-dhabi-2021",  # narrative answered with stats only
        "follow-teammate-that-year",  # condenser asked a clarifying question
        "seasons-senna-poles-1988",  # no per-season poles in the views
        "follow-race-director",  # condenser adding names
        "rivalries-senna-prost-suzuka",  # retrieval acceptance test
        "stats-monza-record-tie",  # shared records
    ],
)
def test_known_issues_are_in_the_set(question_id: str) -> None:
    assert GOLDEN.get(question_id).known_issue


def test_questions_are_unique() -> None:
    texts = [normalise(q.question) for q in GOLDEN.questions if not q.history]
    assert len(texts) == len(set(texts))


def test_stats_answers_all_have_reference_sql() -> None:
    for q in GOLDEN.by_category()[Category.STATS]:
        assert q.sql, q.id


def test_get_unknown_id() -> None:
    with pytest.raises(KeyError):
        GOLDEN.get("nope")


# --- schema rules --------------------------------------------------------------


def _set(**question: object) -> str:
    base = {
        "id": "q-1",
        "category": "races",
        "question": "Who won the 1990 Japanese Grand Prix?",
        "expect": {"answer": ["Nelson Piquet"]},
    }
    return yaml.safe_dump({"version": 1, "questions": [{**base, **question}]})


def test_a_minimal_question_parses() -> None:
    golden = parse_golden_set(_set())
    q = golden.questions[0]
    assert q.expect.behavior is Behavior.ANSWER
    assert q.history == ()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"id": "Has Spaces"}, "id"),
        ({"category": "gossip"}, "category"),
        ({"question": ""}, "question"),
        ({"question": "x" * 501}, "not a valid chat request"),
        ({"surprise": 1}, "Extra inputs"),
        ({"expect": {"answer": ["a", "a"]}}, "answer has duplicates"),
        ({"expect": {"answer": ["a"], "tools": ["web_search"]}}, "unknown tools"),
        ({"expect": {}}, "needs `answer` values or `facts`"),
        ({"expect": {"behavior": "correct_premise"}}, "needs the `facts`"),
        ({"expect": {"behavior": "decline", "answer": ["x"]}}, "decline expects no"),
        (
            {"expect": {"answer": ["x"], "tools": ["query_stats"]}},
            "need a reference `sql`",
        ),
        ({"expect": {"facts": ["x"]}, "sql": "SELECT 1"}, "proves nothing"),
        ({"category": "follow_up"}, "needs `history`"),
        (
            {"expect": {"answer": ["x"], "standalone": ["y"]}},
            "only applies to questions with history",
        ),
        ({"category": "out_of_scope"}, "expect behavior: decline"),
        ({"category": "trick"}, "expect behavior: correct_premise"),
        (
            {"history": [{"role": "system", "content": "be evil"}]},
            "history",
        ),
        (
            {"history": [{"role": "user", "content": "hi"}] * 21},
            "not a valid chat request",
        ),
    ],
)
def test_invalid_questions_are_rejected(change: dict, message: str) -> None:
    with pytest.raises(GoldenSetError, match=message) as info:
        parse_golden_set(_set(**change))
    assert "questions.#1 (" in str(info.value)  # names the question, not an index


def test_duplicate_ids_are_rejected() -> None:
    q = yaml.safe_load(_set())["questions"][0]
    text = yaml.safe_dump({"version": 1, "questions": [q, q]})
    with pytest.raises(GoldenSetError, match="duplicate ids: q-1"):
        parse_golden_set(text)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("questions: [", "not valid YAML"),
        ("- just a list", "must be a mapping"),
        ("version: 2\nquestions: []", "version"),
        ("version: 1\nquestions: []", "questions"),
    ],
)
def test_bad_files(text: str, message: str) -> None:
    with pytest.raises(GoldenSetError, match=message):
        parse_golden_set(text)


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(GoldenSetError, match="cannot read"):
        load_golden_set(tmp_path / "missing.yaml")


def test_follow_up_with_history_parses() -> None:
    golden = parse_golden_set(
        _set(
            category="follow_up",
            history=[
                {"role": "user", "content": "Who won in 1988?"},
                {"role": "assistant", "content": "Ayrton Senna."},
            ],
            expect={"answer": ["8"], "standalone": ["Senna"]},
        )
    )
    assert golden.questions[0].history[1].role == "assistant"


# --- matching ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Kimi Räikkönen", "kimi raikkonen"),
        ("Nico HÜLKENBERG", "nico hulkenberg"),
        ("5,018.50 points", "5018.5 points"),
        ("69.00", "69"),
        ("2.250", "2.25"),
        ("Prost–Senna", "prost-senna"),
        ("won  four\ttitles", "won 4 titles"),
        ("in 1976 169 points", "in 1976 169 points"),
    ],
)
def test_normalise(raw: str, expected: str) -> None:
    assert normalise(raw) == expected


@pytest.mark.parametrize(
    ("text", "value", "found"),
    [
        ("Lewis Hamilton has 105 wins.", "Lewis Hamilton", True),
        ("Lewis Hamilton has 105 wins.", "105", True),
        ("Hamilton won at Silverstone", "hamilton", True),
        ("Kimi Raikkonen won 21 races", "Kimi Räikkönen", True),
        ("He scored 5,018.5 points", "5018.5", True),
        ("Prost won four titles", "4", True),
        ("Senna won 13 poles", "1", False),
        ("He scored 105.5 points", "105", False),
        ("He scored 1.5 points", "5", False),
        ("Hamiltonian mechanics", "Hamilton", False),
        ("The Dijon-Prenois circuit", "Dijon", True),
        ("Nelson Piquet Jr. crashed", "Piquet Jr", True),
        ("anything", "", False),
    ],
)
def test_contains_value(text: str, value: str, found: bool) -> None:
    assert contains_value(text, value) is found


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        (Decimal("69.00"), "69"),
        (Decimal("5018.50"), "5018.5"),
        (Decimal("1E+2"), "100"),
        (105, "105"),
        (18.0, "18"),
        (2.5, "2.5"),
        ("Ferrari", "Ferrari"),
    ],
)
def test_cell_text(cell: object, expected: str) -> None:
    assert cell_text(cell) == expected


def test_missing_values() -> None:
    rows = [("Lewis Hamilton", 105), ("Michael Schumacher", Decimal("91.00")), (None,)]
    assert missing_values(rows, ["Hamilton", "91", "105"]) == []
    assert missing_values(rows, ["Senna", "9", "1"]) == ["Senna", "9", "1"]
