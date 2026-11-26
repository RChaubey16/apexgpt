"""The golden question set (F6.1): schema, loader and answer matching.

The questions live in ``eval/golden.yaml`` at the repository root. Each one says
what a good answer contains, so the eval runner (F6.2) can score answers:

- ``answer``: values that must appear in the answer text (exact match after
  normalising, see :func:`contains_value`). Stats questions carry a reference
  ``sql`` query, and the corpus test checks every value against its rows, so the
  expected answers come from the data, not from memory.
- ``facts``: key points an LLM judge checks the answer against.
- ``sources``: Wikipedia article titles; a good answer cites at least one.
- ``tools``: tools the answer must use.
- ``behavior``: ``answer``, ``decline`` (out of scope) or ``correct_premise``
  (the question assumes something false).
- ``standalone``: for follow-ups, values the rewritten question must contain.

Usage::

    from evals.golden import load_golden_set
    golden = load_golden_set()          # validates everything, raises GoldenSetError
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from app.api.routes.chat import ChatMessage, ChatRequest
from app.tools.knowledge import NAME as KNOWLEDGE_TOOL
from app.tools.stats import NAME as STATS_TOOL

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "eval" / "golden.yaml"

TOOLS = frozenset({STATS_TOOL, KNOWLEDGE_TOOL})

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Category(StrEnum):
    STATS = "stats"
    SEASONS = "seasons"
    RACES = "races"
    CRASHES = "crashes"
    RIVALRIES = "rivalries"
    MULTI_HOP = "multi_hop"
    FOLLOW_UP = "follow_up"
    TRICK = "trick"
    OUT_OF_SCOPE = "out_of_scope"


class Behavior(StrEnum):
    ANSWER = "answer"
    DECLINE = "decline"
    CORRECT_PREMISE = "correct_premise"


class GoldenSetError(ValueError):
    """The golden set file is missing, unreadable or invalid."""


class Expectation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    behavior: Behavior = Behavior.ANSWER
    answer: tuple[Text, ...] = ()
    facts: tuple[Text, ...] = ()
    sources: tuple[Text, ...] = ()
    tools: tuple[Text, ...] = ()
    standalone: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> Expectation:
        for field in ("answer", "facts", "sources", "tools", "standalone"):
            values = getattr(self, field)
            if len(set(values)) != len(values):
                raise ValueError(f"{field} has duplicates")
        unknown = set(self.tools) - TOOLS
        if unknown:
            raise ValueError(
                f"unknown tools {sorted(unknown)}; expected some of {sorted(TOOLS)}"
            )
        if self.behavior is Behavior.ANSWER and not (self.answer or self.facts):
            raise ValueError("an answer needs `answer` values or `facts` to check")
        if self.behavior is Behavior.CORRECT_PREMISE and not self.facts:
            raise ValueError("correct_premise needs the `facts` that correct it")
        if self.behavior is Behavior.DECLINE and (self.answer or self.sources):
            raise ValueError("decline expects no `answer` values or `sources`")
        return self


class GoldenQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]
    category: Category
    question: Text
    history: tuple[ChatMessage, ...] = ()
    expect: Expectation
    sql: Text | None = None
    known_issue: Text | None = None
    # In the production smoke test (F7.4): checked without the LLM judge.
    smoke: bool = False

    @model_validator(mode="after")
    def _check(self) -> GoldenQuestion:
        # The question must be one the chat endpoint accepts as sent.
        try:
            ChatRequest(question=self.question, history=list(self.history))
        except ValidationError as exc:
            reason = exc.errors()[0]["msg"]
            raise ValueError(f"not a valid chat request: {reason}") from None
        if self.category is Category.FOLLOW_UP and not self.history:
            raise ValueError("a follow_up question needs `history`")
        if self.expect.standalone and not self.history:
            raise ValueError("`standalone` only applies to questions with history")
        if STATS_TOOL in self.expect.tools:
            if not self.sql:
                raise ValueError(f"questions using {STATS_TOOL} need a reference `sql`")
            if not self.expect.answer:
                raise ValueError("`sql` proves `answer` values; give at least one")
        if self.sql and not self.expect.answer:
            raise ValueError("`sql` without `answer` values proves nothing")
        if self.smoke and (
            self.expect.behavior is not Behavior.ANSWER
            or not (self.expect.answer or self.expect.sources or self.expect.standalone)
        ):
            raise ValueError(
                "smoke questions need deterministic checks: answer values, sources "
                "or standalone, with behavior answer"
            )
        if self.category is Category.OUT_OF_SCOPE and (
            self.expect.behavior is not Behavior.DECLINE
        ):
            raise ValueError("out_of_scope questions expect behavior: decline")
        if self.category is Category.TRICK and (
            self.expect.behavior is not Behavior.CORRECT_PREMISE
        ):
            raise ValueError("trick questions expect behavior: correct_premise")
        return self


class GoldenSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1]
    questions: tuple[GoldenQuestion, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> GoldenSet:
        dupes = [i for i, n in Counter(q.id for q in self.questions).items() if n > 1]
        if dupes:
            raise ValueError(f"duplicate ids: {', '.join(sorted(dupes))}")
        return self

    def by_category(self) -> dict[Category, list[GoldenQuestion]]:
        grouped: dict[Category, list[GoldenQuestion]] = {c: [] for c in Category}
        for q in self.questions:
            grouped[q.category].append(q)
        return grouped

    def get(self, question_id: str) -> GoldenQuestion:
        for q in self.questions:
            if q.id == question_id:
                return q
        raise KeyError(question_id)


def parse_golden_set(text: str) -> GoldenSet:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise GoldenSetError(f"golden set is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise GoldenSetError(
            "golden set must be a mapping with `version` and `questions`"
        )
    try:
        return GoldenSet.model_validate(data)
    except ValidationError as exc:
        raise GoldenSetError(_describe(exc, data)) from exc


def load_golden_set(path: Path = DEFAULT_PATH) -> GoldenSet:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GoldenSetError(f"cannot read the golden set at {path}: {exc}") from exc
    return parse_golden_set(text)


def _describe(exc: ValidationError, data: dict) -> str:
    """Name the question (by id) and field of each error, not just a list index."""
    questions = data.get("questions") if isinstance(data.get("questions"), list) else []
    lines = []
    for error in exc.errors():
        loc = list(error["loc"])
        if len(loc) >= 2 and loc[0] == "questions" and isinstance(loc[1], int):
            index = loc[1]
            item = questions[index] if index < len(questions) else None
            qid = item.get("id") if isinstance(item, dict) else None
            loc[1] = f"#{index + 1}" + (f" ({qid})" if qid else "")
        where = ".".join(str(part) for part in loc) or "(root)"
        lines.append(f"{where}: {error['msg']}")
    return "invalid golden set:\n  " + "\n  ".join(lines)


# --- Answer matching -------------------------------------------------------

_THOUSANDS = re.compile(r"(?<=\d)[,  ](?=\d{3}\b)")
_WHOLE_DECIMAL = re.compile(r"(?<=\d)\.0+\b")
_TRAILING_ZEROS = re.compile(r"(\.\d*?[1-9])0+\b")
_DASHES = re.compile(r"[‐-―−]")
_NUMBER_WORDS = {
    word: str(n)
    for n, word in enumerate(
        [
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
            "thirteen",
            "fourteen",
            "fifteen",
            "sixteen",
            "seventeen",
            "eighteen",
            "nineteen",
            "twenty",
        ]
    )
}
_NUMBER_WORD = re.compile(r"\b(" + "|".join(_NUMBER_WORDS) + r")\b")


def normalise(text: str) -> str:
    """Fold case, accents, dashes, number words, thousands separators and spacing.

    "Kimi Räikkönen" → "kimi raikkonen"; "5,018.50" → "5018.5"; "69.00" → "69";
    "four titles" → "4 titles". Number words go up to twenty, so a small expected
    number can also match "one of the…"; prefer larger or more specific values.
    """
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = _DASHES.sub("-", text.casefold())
    text = _NUMBER_WORD.sub(lambda m: _NUMBER_WORDS[m.group(1)], text)
    text = _THOUSANDS.sub("", text)
    text = _WHOLE_DECIMAL.sub("", text)
    text = _TRAILING_ZEROS.sub(r"\1", text)
    return " ".join(text.split())


def contains_value(text: str, value: str) -> bool:
    """Whether ``value`` appears in ``text`` as whole words, after normalising.

    "Hamilton" matches "Lewis Hamilton won"; "1" does not match "13".
    """
    needle = normalise(value)
    if not needle:
        return False
    pattern = r"(?<![\w.])" + re.escape(needle) + r"(?![\w]|\.\d)"
    return re.search(pattern, normalise(text)) is not None


def cell_text(value: object) -> str:
    """A database cell as answer text: 69.00 → "69", 5018.50 → "5018.5"."""
    if isinstance(value, Decimal):
        value = value.normalize()
        return format(value, "f")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def missing_values(
    rows: Iterable[Iterable[object]], values: Iterable[str]
) -> list[str]:
    """Expected values that no cell of ``rows`` contains."""
    cells = [cell_text(cell) for row in rows for cell in row if cell is not None]
    return [v for v in values if not any(contains_value(c, v) for c in cells)]
