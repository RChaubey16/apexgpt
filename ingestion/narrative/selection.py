"""Choose the Wikipedia articles for the narrative corpus, and how much of each.

Rules (docs/DATA-STRATEGY.md §2b), computed from the Phase 1 data:

| Article set                        | Depth   |
|------------------------------------|---------|
| Season articles                    | full    |
| Grand Prix race reports            | race    (lead + background + race report)
| Notable drivers                    | full    |
| Other drivers                      | lead    |
| Major constructors                 | full    |
| Minor constructors                 | lead    |
| Circuits                           | circuit (lead + history)
| Curated topics (topics.yaml)       | full    |

- Notable driver: World Champion, race winner, podium finisher, or 30+ starts.
- Major constructor: Constructors' Champion, race winner, or 5+ seasons entered.
  Several constructor rows can share one article (Cooper-Climax, Cooper-Maserati
  -> Cooper Car Company); the rule is applied to the article, over all of them.

Article titles come from each entity's Wikipedia URL, so no names are guessed.
Where a source URL has gone stale (it now lands on a disambiguation page, e.g.
"Tony Brooks" -> "Tony Brooks (racing driver)"), narrative/title_overrides.csv
gives the right title, keyed by ref. Entities sharing an article are merged into
one entry (ids unioned, deepest depth kept). A topic naming an article that's already selected upgrades it to
full text and tags it with the topic group.

`resolve_selection` then asks MediaWiki for each title's current page: missing
pages and disambiguation pages are dropped, and titles redirecting to the same
page are merged. Which sections a depth keeps is the cleaner's job (F2.3).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, ConfigDict

from narrative.errors import SelectionError
from narrative.topics import Topic
from narrative.wiki import PageRef, WikiClient, validate_title

logger = logging.getLogger(__name__)

NOTABLE_MIN_STARTS = 30
MAJOR_MIN_SEASONS = 5

# Non-article namespaces on English Wikipedia (and their aliases), lower case.
_NAMESPACES = {
    "media",
    "special",
    "talk",
    "user",
    "user talk",
    "wikipedia",
    "wikipedia talk",
    "wp",
    "wt",
    "project",
    "project talk",
    "file",
    "file talk",
    "image",
    "image talk",
    "mediawiki",
    "mediawiki talk",
    "template",
    "template talk",
    "help",
    "help talk",
    "category",
    "category talk",
    "portal",
    "portal talk",
    "draft",
    "draft talk",
    "timedtext",
    "timedtext talk",
    "module",
    "module talk",
}


class Kind(StrEnum):
    SEASON = "season"
    RACE = "race"
    DRIVER = "driver"
    CONSTRUCTOR = "constructor"
    CIRCUIT = "circuit"
    TOPIC = "topic"


class Depth(StrEnum):
    FULL = "full"  # the whole article
    RACE = "race"  # lead + background + race report sections
    CIRCUIT = "circuit"  # lead + history sections
    LEAD = "lead"  # the intro paragraphs only


def merge_depth(a: Depth, b: Depth) -> Depth:
    """The deeper of two depths; two different section sets become full."""
    if a == b:
        return a
    if Depth.LEAD in (a, b):
        return b if a == Depth.LEAD else a
    return Depth.FULL


class Selected(BaseModel):
    """One article to fetch, with the metadata its chunks will carry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str
    kinds: tuple[Kind, ...]
    depth: Depth
    season: int | None = None
    race_id: int | None = None
    circuit_id: int | None = None
    driver_ids: tuple[int, ...] = ()
    constructor_ids: tuple[int, ...] = ()
    topic: str | None = None
    # URL fragment ("Circuit" in .../Las_Vegas_Grand_Prix#Circuit): the part
    # of the article the entity is about. A hint for the cleaner.
    anchor: str | None = None
    # Set by resolve_selection: the page the title currently resolves to.
    pageid: int | None = None


def _agree[T](a: T | None, b: T | None) -> T | None:
    """Keep a single-valued field when both sides agree (or one is unset)."""
    if a is None:
        return b
    if b is None or a == b:
        return a
    return None


def merge(a: Selected, b: Selected) -> Selected:
    """Combine two entries for the same article (keeps a's title)."""
    if a.topic and b.topic and a.topic != b.topic:
        raise SelectionError(
            f"{a.title!r} is listed under two topic groups ({a.topic}, {b.topic})"
        )
    return a.model_copy(
        update={
            "kinds": tuple(k for k in Kind if k in set(a.kinds) | set(b.kinds)),
            "depth": merge_depth(a.depth, b.depth),
            "season": _agree(a.season, b.season),
            "race_id": _agree(a.race_id, b.race_id),
            "circuit_id": _agree(a.circuit_id, b.circuit_id),
            "driver_ids": tuple(sorted(set(a.driver_ids) | set(b.driver_ids))),
            "constructor_ids": tuple(
                sorted(set(a.constructor_ids) | set(b.constructor_ids))
            ),
            "topic": a.topic or b.topic,
            "anchor": _agree(a.anchor, b.anchor),
            "pageid": _agree(a.pageid, b.pageid),
        }
    )


def title_from_url(url: str) -> tuple[str, str | None]:
    """(article title, fragment) from an English Wikipedia article URL.

    Raises ValueError for anything that isn't an article on en.wikipedia.org.
    """
    parts = urlsplit(url.strip())
    if (
        parts.scheme not in ("http", "https")
        or (parts.hostname or "").lower() != "en.wikipedia.org"
        or not parts.path.startswith("/wiki/")
        or parts.query
    ):
        raise ValueError("not an English Wikipedia article URL")
    title = validate_title(unquote(parts.path.removeprefix("/wiki/")))
    namespace, colon, _ = title.partition(":")
    if colon and namespace.strip().lower() in _NAMESPACES:
        raise ValueError(f"not an article (a {namespace} page)")
    anchor = " ".join(unquote(parts.fragment).replace("_", " ").split()) or None
    return title, anchor


# --- rows read from the structured data ---


@dataclass(frozen=True)
class SeasonRow:
    year: int
    url: str | None


@dataclass(frozen=True)
class RaceRow:
    race_id: int
    season: int
    circuit_id: int
    name: str
    url: str | None


@dataclass(frozen=True)
class CircuitRow:
    circuit_id: int
    name: str
    url: str | None


@dataclass(frozen=True)
class DriverRow:
    driver_id: int
    name: str
    url: str | None
    championships: int = 0
    wins: int = 0
    podiums: int = 0
    starts: int = 0


@dataclass(frozen=True)
class ConstructorRow:
    constructor_id: int
    name: str
    url: str | None
    seasons: frozenset[int] = frozenset()
    wins: int = 0
    champion: bool = False


@dataclass
class EntityRows:
    seasons: list[SeasonRow] = field(default_factory=list)
    races: list[RaceRow] = field(default_factory=list)
    circuits: list[CircuitRow] = field(default_factory=list)
    drivers: list[DriverRow] = field(default_factory=list)
    constructors: list[ConstructorRow] = field(default_factory=list)
    # ref -> id, for resolving the refs in topics.yaml
    driver_refs: dict[str, int] = field(default_factory=dict)
    constructor_refs: dict[str, int] = field(default_factory=dict)
    circuit_refs: dict[str, int] = field(default_factory=dict)


def is_notable_driver(row: DriverRow) -> bool:
    return (
        row.championships > 0
        or row.wins > 0
        or row.podiums > 0
        or row.starts >= NOTABLE_MIN_STARTS
    )


def is_major_constructor(rows: Sequence[ConstructorRow]) -> bool:
    """Applied to all the constructor rows that share one article."""
    seasons: set[int] = set().union(*(r.seasons for r in rows))
    return (
        any(r.champion for r in rows)
        or any(r.wins > 0 for r in rows)
        or len(seasons) >= MAJOR_MIN_SEASONS
    )


@dataclass(frozen=True)
class Skipped:
    source: str  # e.g. "driver 763 (Thomas Monarch)"
    reason: str


@dataclass(frozen=True)
class TitleOverride:
    """A curated title for an entity whose source URL is stale (title_overrides.csv)."""

    kind: Kind  # driver, constructor or circuit
    ref: str
    title: str


OVERRIDABLE_KINDS = (Kind.DRIVER, Kind.CONSTRUCTOR, Kind.CIRCUIT)


@dataclass
class Selection:
    articles: list[Selected]
    skipped: list[Skipped] = field(default_factory=list)
    # Hand-written titles (topics, overrides): must resolve to a real article.
    curated: set[str] = field(default_factory=set)


class _Collector:
    """Accumulates entries by title, merging the ones for the same article."""

    def __init__(self, overrides: dict[tuple[Kind, int], str]) -> None:
        self.by_title: dict[str, Selected] = {}
        self.skipped: list[Skipped] = []
        self.problems: list[str] = []
        self.curated: set[str] = set()
        self._overrides = overrides

    def url_title(
        self,
        source: str,
        url: str | None,
        override_key: tuple[Kind, int] | None = None,
    ) -> tuple[str, str | None] | None:
        override = self._overrides.get(override_key) if override_key else None
        if override is not None:
            try:
                if url and title_from_url(url)[0] == override:
                    self.problems.append(
                        f"title_overrides.csv: {source} already links to {override!r}"
                    )
            except ValueError:
                pass  # overriding an unusable URL is what overrides are for
            self.curated.add(override)
            return override, None
        if not url:
            self.skipped.append(Skipped(source, "no Wikipedia URL"))
            return None
        try:
            return title_from_url(url)
        except ValueError as exc:
            self.skipped.append(Skipped(source, str(exc)))
            return None

    def add(self, entry: Selected) -> None:
        existing = self.by_title.get(entry.title)
        self.by_title[entry.title] = (
            entry if existing is None else merge(existing, entry)
        )


def select_articles(
    rows: EntityRows,
    topics: Iterable[Topic],
    overrides: Iterable[TitleOverride] = (),
) -> Selection:
    """Apply the selection rules to the structured data and the curated lists."""
    unknown: list[str] = []
    refs = {
        Kind.DRIVER: rows.driver_refs,
        Kind.CONSTRUCTOR: rows.constructor_refs,
        Kind.CIRCUIT: rows.circuit_refs,
    }
    by_id: dict[tuple[Kind, int], str] = {}
    for o in overrides:
        if o.ref in refs[o.kind]:
            by_id[(o.kind, refs[o.kind][o.ref])] = o.title
        else:
            unknown.append(f"title_overrides.csv: unknown {o.kind} ref {o.ref!r}")
    out = _Collector(by_id)

    for s in rows.seasons:
        if found := out.url_title(f"season {s.year}", s.url):
            title, anchor = found
            out.add(
                Selected(
                    title=title,
                    kinds=(Kind.SEASON,),
                    depth=Depth.FULL,
                    season=s.year,
                    anchor=anchor,
                )
            )

    for r in rows.races:
        if found := out.url_title(f"race {r.race_id} ({r.season} {r.name})", r.url):
            title, anchor = found
            out.add(
                Selected(
                    title=title,
                    kinds=(Kind.RACE,),
                    depth=Depth.RACE,
                    season=r.season,
                    race_id=r.race_id,
                    circuit_id=r.circuit_id,
                    anchor=anchor,
                )
            )

    for c in rows.circuits:
        if found := out.url_title(
            f"circuit {c.circuit_id} ({c.name})",
            c.url,
            (Kind.CIRCUIT, c.circuit_id),
        ):
            title, anchor = found
            out.add(
                Selected(
                    title=title,
                    kinds=(Kind.CIRCUIT,),
                    depth=Depth.CIRCUIT,
                    circuit_id=c.circuit_id,
                    anchor=anchor,
                )
            )

    for d in rows.drivers:
        if found := out.url_title(
            f"driver {d.driver_id} ({d.name})", d.url, (Kind.DRIVER, d.driver_id)
        ):
            title, anchor = found
            out.add(
                Selected(
                    title=title,
                    kinds=(Kind.DRIVER,),
                    depth=Depth.FULL if is_notable_driver(d) else Depth.LEAD,
                    driver_ids=(d.driver_id,),
                    anchor=anchor,
                )
            )

    # Constructors: group rows by article first, then apply the rule per article.
    groups: dict[str, list[tuple[ConstructorRow, str | None]]] = defaultdict(list)
    for k in rows.constructors:
        source = f"constructor {k.constructor_id} ({k.name})"
        if found := out.url_title(source, k.url, (Kind.CONSTRUCTOR, k.constructor_id)):
            title, anchor = found
            groups[title].append((k, anchor))
    for title, members in groups.items():
        depth = (
            Depth.FULL if is_major_constructor([m for m, _ in members]) else Depth.LEAD
        )
        anchors = {a for _, a in members}
        out.add(
            Selected(
                title=title,
                kinds=(Kind.CONSTRUCTOR,),
                depth=depth,
                constructor_ids=tuple(sorted(m.constructor_id for m, _ in members)),
                anchor=anchors.pop() if len(anchors) == 1 else None,
            )
        )

    for t in topics:
        out.curated.add(t.title)
        driver_ids = _ids(t.drivers, rows.driver_refs, "driver", t.title, unknown)
        constructor_ids = _ids(
            t.constructors, rows.constructor_refs, "constructor", t.title, unknown
        )
        circuit_ids = _ids(
            [t.circuit] if t.circuit else [],
            rows.circuit_refs,
            "circuit",
            t.title,
            unknown,
        )
        out.add(
            Selected(
                title=t.title,
                kinds=(Kind.TOPIC,),
                depth=Depth.FULL,
                season=t.season,
                circuit_id=circuit_ids[0] if circuit_ids else None,
                driver_ids=driver_ids,
                constructor_ids=constructor_ids,
                topic=t.group,
            )
        )
    if unknown or out.problems:
        raise SelectionError(
            "the curated lists don't match the structured data:\n  "
            + "\n  ".join(unknown + out.problems)
        )

    articles = sorted(out.by_title.values(), key=lambda a: a.title)
    return Selection(articles=articles, skipped=out.skipped, curated=out.curated)


def _ids(
    refs: Sequence[str],
    known: dict[str, int],
    what: str,
    title: str,
    unknown: list[str],
) -> tuple[int, ...]:
    ids = []
    for ref in refs:
        if ref in known:
            ids.append(known[ref])
        else:
            unknown.append(f"{title!r}: unknown {what} ref {ref!r}")
    return tuple(sorted(set(ids)))


# --- resolving titles against Wikipedia ---


@dataclass
class Resolution:
    articles: list[Selected]
    missing: list[Selected] = field(default_factory=list)
    disambiguation: list[Selected] = field(default_factory=list)
    # (requested title, page title it was merged into)
    merged: list[tuple[str, str]] = field(default_factory=list)


def resolve_selection(
    articles: Sequence[Selected],
    client: WikiClient,
    curated: Collection[str] = (),
) -> Resolution:
    """Map titles to current pages; drop missing/disambiguation; merge duplicates.

    Curated titles (topics, and `curated`: the title overrides) must resolve to
    a real article, and each topic exactly once: anything else is a mistake in
    topics.yaml or title_overrides.csv and raises SelectionError.
    """

    def is_curated(article: Selected) -> bool:
        return Kind.TOPIC in article.kinds or article.title in curated

    pages = client.current_revisions(a.title for a in articles)
    result = Resolution(articles=[])
    by_page: dict[int, Selected] = {}
    topic_titles: dict[int, list[str]] = defaultdict(list)
    for article in articles:
        ref: PageRef | None = pages.get(article.title)
        if ref is None:
            result.missing.append(article)
            continue
        if ref.disambiguation:
            result.disambiguation.append(article)
            continue
        if Kind.TOPIC in article.kinds:
            topic_titles[ref.pageid].append(article.title)
        resolved = article.model_copy(update={"title": ref.title, "pageid": ref.pageid})
        existing = by_page.get(ref.pageid)
        if existing is None:
            by_page[ref.pageid] = resolved
        else:
            by_page[ref.pageid] = merge(existing, resolved)
            result.merged.append((article.title, ref.title))

    problems = [
        f"{a.title!r} is not on Wikipedia" for a in result.missing if is_curated(a)
    ]
    problems += [
        f"{a.title!r} is a disambiguation page"
        for a in result.disambiguation
        if is_curated(a)
    ]
    problems += [
        f"{' and '.join(repr(t) for t in titles)} are the same article"
        for titles in topic_titles.values()
        if len(titles) > 1
    ]
    if problems:
        raise SelectionError(
            "fix these curated titles (topics.yaml, title_overrides.csv):\n  "
            + "\n  ".join(problems)
        )

    result.articles = sorted(by_page.values(), key=lambda a: a.title)
    return result


def summarise(articles: Sequence[Selected]) -> dict[str, dict[str, int]]:
    """Counts by depth and by kind (an article can have several kinds)."""
    depths = {d.value: 0 for d in Depth}
    kinds = {k.value: 0 for k in Kind}
    for a in articles:
        depths[a.depth.value] += 1
        for k in a.kinds:
            kinds[k.value] += 1
    return {"depth": depths, "kind": kinds}
