"""Turn a fetched Wikipedia article (rendered HTML) into clean prose by section.

Removed everywhere (docs/DATA-STRATEGY.md §2a):

- all tables: classification and standings tables, results grids, and the page
  furniture built from tables (infoboxes, navboxes, succession and maintenance
  boxes); the structured data already holds the numbers;
- page furniture: navboxes, hatnotes, images and captions, quote boxes,
  references lists, stub and maintenance notices, inline styles;
- citation markers ("[1]", "[a]", "[citation needed]");
- boilerplate sections (References, See also, Racing record, Helmet, ...),
  results/classification sections, and table notes left behind ("Source: ...").

Then the article's depth (from the selection) decides which sections are kept:

- full: every section;
- race: the lead + background and race report sections, i.e. everything but
  the practice / qualifying / sprint / entry-list sections;
- circuit: the lead + history and track sections (+ the section the URL named);
- lead: the intro only.

The result keeps each section's heading path ("Race", "Lap 1") so the chunker
can split on section boundaries and label chunks.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass, field

from lxml import etree
from lxml import html as lxml_html

from narrative.selection import Depth

# Section headings are matched after lower-casing and collapsing whitespace.
BOILERPLATE_SECTIONS = frozenset(
    {
        "references",
        "notes",
        "footnotes",
        "citations",
        "sources",
        "notes and references",
        "references and notes",
        "works cited",
        "bibliography",
        "further reading",
        "external links",
        "see also",
        "gallery",
        "helmet",
        "career summary",
        "classification",
        "race classification",
        "qualifying classification",
        "sprint classification",
        "sprint qualifying classification",
        "championship standings after the race",
        "final championship standings",
        "starting grid",
        "box score",
        "books",
        "publications",
        "filmography",
        "discography",
        "films and books",
    }
)
# ... and any heading matching these (results tables, records).
_BOILERPLATE_PATTERN = re.compile(
    r"^complete\b|\bresults$|\brecords?$|\bstandings$|^lap times$|\breferences\b"
    r"|^(?:list of )?(?:selected )?works$"
)

# Race reports keep everything except the session and entry-list sections
# (practice, qualifying, sprint, ...): background, the race, post-race,
# controversies and reactions all stay, whatever the article calls them.
_RACE_SKIP = re.compile(
    r"practice|qualifying|warm-up|warmup|sprint|time trials|shootout"
    r"|friday drivers|shared drives?|broadcast|permutations|^entries$|^entry list$"
    r"|drivers' championship|^winner$|^attendees$|additional information"
)
# Circuits keep the history and track sections (+ the section the URL named).
CIRCUIT_SECTIONS = frozenset(
    {
        "history",
        "circuit history",
        "track history",
        "layout history",
        "racing history",
        "fatalities",
        "fatal accidents",
        "deaths",
        "deaths from crashes",
        "circuit",
        "the circuit",
        "track",
        "layout",
        "description",
        "characteristics",
        "design",
    }
)

# Elements removed before any text is read. Matched on whole class names.
_REMOVE_CLASSES = (
    "navbox",
    "navbox-styles",
    "hatnote",
    "shortdescription",
    "mw-references-wrap",
    "reflist",
    "references",
    "metadata",
    "ambox",
    "side-box",
    "sistersitebox",
    "portalborder",
    "noprint",
    "mw-empty-elt",
    "toc",
    "asbox",
    "authority-control",
    "mw-editsection",
    "gallery",
    "navigation-not-searchable",
    "motorsport-season-nav",
    "infobox",
    "pullquote",
    "thumb",
    "flagicon",
    "mw-cite-backlink",
    "reference",
    "Inline-Template",
)
_REMOVE_TAGS = ("style", "script", "link", "meta", "noscript", "table", "figure", "img")


def _has_class(name: str) -> str:
    return f"contains(concat(' ', normalize-space(@class), ' '), ' {name} ')"


_REMOVE_XPATH = etree.XPath(
    " | ".join(
        [f"//{tag}" for tag in _REMOVE_TAGS]
        + [f"//*[{_has_class(c)}]" for c in _REMOVE_CLASSES]
        # Coordinates (geo-inline, geo-default, geo-dms, ...).
        + ["//*[starts-with(@class, 'geo') or contains(@class, ' geo')]"]
        + ["//comment()"]
    )
)
# Invisible characters left by templates (zero-width spaces, BOMs, soft hyphens).
_INVISIBLE = dict.fromkeys(map(ord, "​‌‍⁠﻿­"))

_HEADING_TAGS = {"h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
# Leftover citation-like markers (e.g. inside quotes copied as plain text).
_CITATION_MARKERS = re.compile(
    r"\[(?:\d+|[a-z]{1,2}|note \d+|nb \d+|citation needed|clarification needed"
    r"|according to whom\?|when\?|who\?|which\?|by whom\?|dubious[^\]]*|failed verification)\]",
    re.IGNORECASE,
)
_WAYBACK = re.compile(r"\s*Archived \d{4}-\d{2}-\d{2} at the Wayback Machine")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?)])")
_SPACE_AFTER_OPEN = re.compile(r"([(])\s+")
# Notes left under removed tables: "Source: ...", "Notes:", "^1 – ...", legends.
_TABLE_NOTE = re.compile(
    r"^(?:\^|sources?\s*:|notes?\s*:?$|note\s*:|bold text indicates|italics indicate"
    r"|only the top (?:five|ten|\w+) positions)",
    re.IGNORECASE,
)
MAX_HTML_BYTES = 20_000_000


class CleanError(ValueError):
    """The article HTML can't be cleaned (empty, oversized, unparseable)."""


@dataclass(frozen=True)
class Section:
    path: tuple[str, ...]  # () is the lead; ("Race", "Lap 1") a subsection
    text: str  # paragraphs separated by a blank line

    @property
    def heading(self) -> str:
        return " > ".join(self.path)


@dataclass
class CleanedArticle:
    sections: list[Section] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(s.text for s in self.sections)

    @property
    def words(self) -> int:
        return sum(len(s.text.split()) for s in self.sections)


def normalise_heading(text: str) -> str:
    return " ".join(text.lower().split())


def is_boilerplate(heading: str) -> bool:
    h = normalise_heading(heading)
    return h in BOILERPLATE_SECTIONS or bool(_BOILERPLATE_PATTERN.search(h))


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text).replace("\xa0", " ").translate(_INVISIBLE)
    text = _CITATION_MARKERS.sub("", text)
    text = _WAYBACK.sub("", text)
    text = " ".join(text.split())
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
    return _SPACE_AFTER_OPEN.sub(r"\1", text)


def _content_root(html: str) -> etree._Element:
    if not html or not html.strip():
        raise CleanError("article HTML is empty")
    if len(html.encode("utf-8")) > MAX_HTML_BYTES:
        raise CleanError("article HTML is unexpectedly large")
    try:
        # A created parent holds any shape: one wrapper div or bare blocks.
        root = lxml_html.fragment_fromstring(html, create_parent="div")
    except (etree.ParserError, ValueError) as exc:
        raise CleanError(f"article HTML can't be parsed: {exc}") from None
    found = root.xpath(f".//div[{_has_class('mw-parser-output')}]")
    return found[0] if found else root


def _blocks(
    element: etree._Element, path: list[str]
) -> Iterator[tuple[tuple[str, ...], str]]:
    """Yield (heading path, text block) for an element's children, in order."""
    for child in element:
        if not isinstance(child.tag, str):
            continue
        tag = child.tag
        heading = child if tag in _HEADING_TAGS else None
        if (
            heading is None
            and tag == "div"
            and "mw-heading" in (child.get("class") or "").split()
        ):
            heading = next((h for h in child if h.tag in _HEADING_TAGS), None)
        if heading is not None:
            level = _HEADING_TAGS[heading.tag]
            del path[level - 2 :]
            while len(path) < level - 2:  # skipped levels (h2 -> h4)
                path.append("")
            path.append(clean_text(heading.text_content()))
            continue
        current = tuple(p for p in path if p)
        if tag == "p" or tag == "blockquote":
            yield current, clean_text(child.text_content())
        elif tag in ("ul", "ol"):
            items = [clean_text(li.text_content()) for li in child if li.tag == "li"]
            lines = [f"- {item}" for item in items if item]
            if lines:
                yield current, "\n".join(lines)
        elif tag == "dl":
            for item in child:
                if item.tag in ("dt", "dd"):
                    yield current, clean_text(item.text_content())
        elif tag in ("div", "section", "center"):
            yield from _blocks(child, path)


def _keep(path: tuple[str, ...], depth: Depth, anchor: str | None) -> bool:
    if any(is_boilerplate(h) for h in path):
        return False
    if not path or depth == Depth.FULL:
        return True
    if depth == Depth.LEAD:
        return False
    if anchor and any(normalise_heading(h) == normalise_heading(anchor) for h in path):
        return True
    top = normalise_heading(path[0])
    if depth == Depth.RACE:
        return not _RACE_SKIP.search(top)
    return top in CIRCUIT_SECTIONS


def clean_article(html: str, depth: Depth, anchor: str | None = None) -> CleanedArticle:
    """Clean rendered article HTML and keep the sections its depth allows."""
    root = _content_root(html)
    for element in _REMOVE_XPATH(root):
        parent = element.getparent()
        if parent is None:
            continue
        # Keep the text that follows a removed inline element ("...won.[1] He").
        tail = element.tail
        previous = element.getprevious()
        if tail:
            if previous is not None:
                previous.tail = (previous.tail or "") + tail
            else:
                parent.text = (parent.text or "") + tail
        parent.remove(element)

    by_path: dict[tuple[str, ...], list[str]] = {}
    for path, text in _blocks(root, []):
        if len(text) < 2 or _TABLE_NOTE.match(text):
            continue
        if not _keep(path, depth, anchor):
            continue
        by_path.setdefault(path, []).append(text)
    return CleanedArticle(
        sections=[
            Section(path, "\n\n".join(blocks)) for path, blocks in by_path.items()
        ]
    )
