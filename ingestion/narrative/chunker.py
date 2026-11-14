"""Split cleaned articles into retrieval chunks, along section boundaries.

Rules (docs/DATA-STRATEGY.md §2c):

- A chunk never mixes two top-level sections, and the lead is always its own
  chunk. Small subsections of one top-level section ("Formula One career >
  Jordan (1991)", "… > Benetton (1991–1995)") are packed together, each under
  its own heading line, so short sections don't become weak one-line chunks.
- A section longer than the target is split into roughly equal parts at
  paragraph boundaries (then sentences, then words, only when a paragraph or a
  sentence is itself too long). Consecutive parts of one section overlap by
  the last sentence or two (~50 tokens); nothing overlaps across sections.
- Sizes are estimated from word counts (see TOKENS_PER_WORD), and every chunk,
  including the "title > section" heading it is embedded with, stays under the
  embedding model's 512-token input.
"""

import math
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

# bge-small-en-v1.5 WordPiece tokens per whitespace-separated word, measured on
# this corpus: mean 1.28, 99th percentile of 350-word windows 1.39. Sizing with
# the high figure keeps nearly every chunk inside the model's input; on average
# chunks are ~10% smaller than their estimate.
TOKENS_PER_WORD = 1.4
# bge-small reads at most 512 tokens, two of them [CLS] and [SEP]. Longer input
# is silently truncated, so the plan's ~400–600 becomes ~350–500 here.
MODEL_MAX_TOKENS = 510
TARGET_TOKENS = 450
MAX_TOKENS = 500
OVERLAP_TOKENS = 50
HEADING_SEPARATOR = " > "
PARAGRAPH = "\n\n"

# Abbreviations that end with a full stop without ending the sentence.
_ABBREVIATIONS = frozenset(
    [
        "mr",
        "mrs",
        "ms",
        "dr",
        "jr",
        "sr",
        "st",
        "mt",
        "no",
        "nos",
        "vs",
        "lt",
        "col",
        "gen",
        "capt",
        "sgt",
        "prof",
        "inc",
        "ltd",
        "co",
        "corp",
        "bros",
        "approx",
        "est",
        "fig",
        "etc",
        "jan",
        "feb",
        "mar",
        "apr",
        "jun",
        "jul",
        "aug",
        "sep",
        "sept",
        "oct",
        "nov",
        "dec",
    ]
)
_SENTENCE_END = re.compile(r"[.!?][\"”’')\]]*\s+(?=[\"“‘'(\[]?[A-Z0-9])")
_LAST_WORD = re.compile(r"(\S+)$")


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text.split()) * TOKENS_PER_WORD)


def split_sentences(text: str) -> list[str]:
    """Split prose into sentences, keeping initials ("J. Clark") and "St. Devote"."""
    sentences: list[str] = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        before = _LAST_WORD.search(text, start, match.start() + 1)
        word = before.group(1).rstrip(".!?\"”’')]").lower() if before else ""
        if text[match.start()] == "." and (
            word in _ABBREVIATIONS or (len(word) == 1 and word.isalpha())
        ):
            continue
        sentences.append(text[start : match.end()].strip())
        start = match.end()
    if tail := text[start:].strip():
        sentences.append(tail)
    return sentences


@dataclass(frozen=True)
class Chunk:
    """One chunk of an article: its section heading path and its text."""

    path: tuple[str, ...]  # () is the lead
    text: str
    tokens: int  # estimated, including the heading


@dataclass(frozen=True)
class _Section:
    path: tuple[str, ...]
    text: str


@dataclass(frozen=True)
class _Unit:
    text: str
    joiner: str = PARAGRAPH  # between this and the previous piece of its section
    whole: bool = True  # a whole paragraph, not a line or sentence of one


@dataclass
class _Draft:
    """A chunk being filled: per section, its pieces and what joins each to the last."""

    parts: list[tuple[tuple[str, ...], list[_Unit]]] = field(default_factory=list)
    tokens: int = 0  # body and heading lines, without the article heading

    def add(self, path: tuple[str, ...], unit: _Unit, tokens: int) -> None:
        if not self.parts or self.parts[-1][0] != path:
            self.parts.append((path, []))
        self.parts[-1][1].append(unit)
        self.tokens += tokens

    @property
    def empty(self) -> bool:
        return not self.parts


class ChunkError(ValueError):
    """An article can't be chunked within the size limits."""


def _common_prefix(paths: Sequence[tuple[str, ...]]) -> tuple[str, ...]:
    prefix = paths[0]
    for path in paths[1:]:
        size = 0
        while size < min(len(prefix), len(path)) and prefix[size] == path[size]:
            size += 1
        prefix = prefix[:size]
    return prefix


def _heading(path: tuple[str, ...]) -> str:
    return HEADING_SEPARATOR.join(path)


def _join(units: Sequence[_Unit]) -> str:
    return units[0].text + "".join(u.joiner + u.text for u in units[1:])


def _render(draft: _Draft) -> tuple[tuple[str, ...], str]:
    paths = [path for path, _ in draft.parts]
    prefix = _common_prefix(paths)
    if len(paths) == 1:
        return prefix, _join(draft.parts[0][1])
    blocks: list[str] = []
    for path, units in draft.parts:
        if tail := path[len(prefix) :]:
            blocks.append(_heading(tail))
        blocks.append(_join(units))
    return prefix, PARAGRAPH.join(blocks)


def _units(text: str, limit: int) -> Iterator[_Unit]:
    """Paragraphs of a section, broken further only where one exceeds the limit."""
    for paragraph in text.split(PARAGRAPH):
        if estimate_tokens(paragraph) <= limit:
            yield _Unit(paragraph)
            continue
        lines = paragraph.split("\n")
        joiner = "\n" if len(lines) > 1 else " "
        pieces = lines if len(lines) > 1 else split_sentences(paragraph)
        for number, piece in enumerate(pieces):
            first = PARAGRAPH if number == 0 else joiner
            if estimate_tokens(piece) <= limit:
                yield _Unit(piece, first, whole=False)
                continue
            words = piece.split()
            step = max(int(limit / TOKENS_PER_WORD), 1)
            for start in range(0, len(words), step):
                yield _Unit(" ".join(words[start : start + step]), first, whole=False)
                first = " "


def _overlap(pieces: Sequence[_Unit]) -> _Unit | None:
    """The last sentences of a part, up to OVERLAP_TOKENS, to start the next one."""
    last = pieces[-1]
    sentences = split_sentences(last.text)
    if last.whole:  # never repeat a whole paragraph
        sentences = sentences[1:]
    kept: list[str] = []
    tokens = 0
    for sentence in reversed(sentences):
        cost = estimate_tokens(sentence)
        if tokens + cost > OVERLAP_TOKENS:
            break
        kept.insert(0, sentence)
        tokens += cost
    return _Unit(" ".join(kept)) if kept else None


def _group(sections: Sequence[_Section]) -> Iterator[list[_Section]]:
    """The lead alone, then runs of sections under the same top-level heading."""
    run: list[_Section] = []
    for section in sections:
        if run and (not section.path or run[0].path[:1] != section.path[:1]):
            yield run
            run = []
        run.append(section)
    if run:
        yield run


def _chunk_group(
    title: str, group: list[_Section], target: int, maximum: int
) -> Iterator[Chunk]:
    # Room for the "title > section" heading, sized for the wordiest path
    # (a chunk's heading is a prefix of one of its sections' paths).
    reserved = max(estimate_tokens(_heading((title, *s.path))) for s in group)
    target -= reserved
    limit = maximum - reserved
    draft = _Draft()

    def finish() -> Chunk:
        path, text = _render(draft)
        tokens = estimate_tokens(_heading((title, *path))) + estimate_tokens(text)
        if tokens > maximum:  # a bug in the packing below, not bad input
            raise ChunkError(f"{title!r}: a {tokens}-token chunk in {path}")
        return Chunk(path, text, tokens)

    for section in group:
        heading_cost = estimate_tokens(_heading(section.path[1:]))
        size = estimate_tokens(section.text) + heading_cost
        if not draft.empty and draft.tokens + size > target:
            yield finish()
            draft = _Draft()
        if draft.tokens + size <= target:
            draft.add(section.path, _Unit(section.text), size)
            continue

        # Too long for one chunk: split into near-equal parts.
        parts = math.ceil(size / target)
        part_target = min(math.ceil(size / parts) + OVERLAP_TOKENS, limit)
        units = list(_units(section.text, limit - heading_cost - OVERLAP_TOKENS))
        costs = [estimate_tokens(unit.text) for unit in units]
        remaining = sum(costs)
        pieces: list[_Unit] = []
        for unit, cost in zip(units, costs, strict=True):
            # Start a new part when this one is full, unless the rest of the
            # section still fits in it (no short leftover part).
            if (
                pieces
                and draft.tokens + cost > part_target
                and draft.tokens + remaining > limit
            ):
                yield finish()
                draft = _Draft()
                draft.tokens = heading_cost
                if (carried := _overlap(pieces)) is not None:
                    draft.add(section.path, carried, estimate_tokens(carried.text))
                pieces = []
            if draft.empty:
                draft.tokens = max(draft.tokens, heading_cost)
            draft.add(section.path, unit, cost)
            pieces.append(unit)
            remaining -= cost
    if not draft.empty:
        yield finish()


def chunk_sections(
    title: str,
    sections: Sequence[tuple[tuple[str, ...], str]],
    *,
    target: int = TARGET_TOKENS,
    maximum: int = MAX_TOKENS,
) -> list[Chunk]:
    """Chunk one article's (heading path, text) sections, in order."""
    if not 0 < target <= maximum <= MODEL_MAX_TOKENS:
        raise ValueError(f"need 0 < target <= maximum <= {MODEL_MAX_TOKENS}")
    items = [_Section(tuple(path), text) for path, text in sections if text.strip()]
    if not items:
        return []
    headings = max(estimate_tokens(_heading((title, *s.path))) for s in items)
    if headings * 4 > target:
        raise ChunkError(f"{title!r}: the section headings are too long to chunk")
    return [
        chunk
        for group in _group(items)
        for chunk in _chunk_group(title, group, target, maximum)
    ]
