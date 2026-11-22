"""Entity resolution: find drivers, constructors and circuits named in a question (F3.4).

    resolver = EntityResolver(session_factory)
    resolution = resolver.resolve("Did Schumi beat Hill at Adelaide in 1994?")
    # Michael Schumacher (nickname), Damon Hill (active in 1994), Adelaide Street Circuit

Where names come from:
- drivers and constructors: the alias tables (generated full names, surnames
  and constructor names, plus curated nicknames; see the F1.3 loader);
- circuits: built here from the `circuits` table (ref, locality, and the name
  without generic words such as "Circuit de" or "International"), plus a few
  curated names the data lacks (CIRCUIT_NICKNAMES).

Matching: the question is normalised word by word with the loader's
`normalise_alias`, then scanned left to right, longest alias first, so
"Michael Schumacher" is one mention, not "Michael" plus "Schumacher".
Single-word aliases that are also everyday words ("pace", "speed", "era") only
count when capitalised in the question, and "March"/"May" never count alone.

Ambiguity is kept: "Schumacher" lists Michael, Ralf and Mick. Candidates are
ordered by (1) active in a season the question names, (2) how strong the match
is (a driver's full name > nickname > a constructor's name = a driver's surname
> a circuit name), (3) career prominence (wins, then races). A team name and a
surname rank equally so prominence decides between a team named after a driver
and the driver: "McLaren" is the team (~180 wins v Bruce's 4), "Prost" the
driver (51 v Prost Grand Prix's 0). The first candidate is the best guess; the
rest stay available.

The index (~2,000 aliases) is loaded once and kept in memory, then reloaded
after `ttl_seconds` so loader updates appear without a restart.
"""

import logging
import re
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.retrieval.errors import SearchError
from app.retrieval.filters import filters_from_query
from app.retrieval.normalise import normalise_alias
from app.retrieval.search import normalise_query

logger = logging.getLogger(__name__)

EntityKind = Literal["driver", "constructor", "circuit"]
MatchKind = Literal["name", "nickname", "circuit", "surname"]

# How strongly a match identifies the entity (used for ordering candidates).
STRENGTH: dict[tuple[str, str], int] = {
    ("driver", "name"): 4,
    ("driver", "nickname"): 3,
    ("constructor", "nickname"): 3,
    ("constructor", "name"): 2,
    ("driver", "surname"): 2,
    ("circuit", "circuit"): 1,
}


def strength(kind: str, match: str) -> int:
    return STRENGTH.get((kind, match), 0)


MAX_CANDIDATES = 5
DEFAULT_TTL_SECONDS = 6 * 3600

# Single-word aliases that are also everyday words in F1 questions. They only
# match when capitalised ("Speed" = Scott Speed, "top speed" = nothing).
# Curated from the aliases that are lowercase words in a dictionary: names that
# are only rare words ("senna", "hunt", "button", "lotus") are left out so a
# lowercase question still finds them.
COMMON_WORDS = frozenset(
    [
        "ball",
        "bar",
        "barber",
        "bell",
        "binder",
        "brown",
        "cannon",
        "charade",
        "courage",
        "craft",
        "crook",
        "cross",
        "driver",
        "duke",
        "elder",
        "era",
        "force",
        "fry",
        "gamble",
        "gaze",
        "gene",
        "green",
        "grim",
        "hall",
        "love",
        "lovely",
        "mass",
        "pace",
        "re",
        "riverside",
        "rose",
        "said",
        "sharp",
        "speed",
        "spirit",
        "stuck",
        "token",
        "ward",
    ]
)
# Never matched as a single word: months are far more common than the teams.
NEVER_ALONE = frozenset({"march", "may"})

# Circuit names people use that the circuits table doesn't contain: alias -> ref.
CIRCUIT_NICKNAMES = {
    "singapore": "marina_bay",
    "cota": "americas",
    "nordschleife": "nurburgring",
    "osterreichring": "zeltweg",
    "a1 ring": "red_bull_ring",
    "catalunya": "catalunya",
    "barcelona catalunya": "catalunya",
}
# Generic words stripped from the start / end of circuit names.
_CIRCUIT_PREFIX = frozenset(
    [
        "circuit",
        "circuito",
        "autodromo",
        "de",
        "do",
        "da",
        "di",
        "del",
        "of",
        "the",
        "internacional",
        "internazionale",
        "nazionale",
    ]
)
_CIRCUIT_SUFFIX = frozenset(
    [
        "circuit",
        "street",
        "international",
        "raceway",
        "speedway",
        "autodrom",
        "autodrome",
        "grand",
        "prix",
    ]
)
_WORD = re.compile(r"[^\W_]+")


class EntityIndexUnavailableError(SearchError):
    """The entity tables could not be read."""


@dataclass(frozen=True)
class Entity:
    kind: EntityKind
    id: int
    ref: str
    name: str
    # Seasons raced (drivers, constructors) or hosted (circuits).
    seasons: frozenset[int] = field(repr=False, compare=False)
    wins: int = 0
    races: int = 0

    @property
    def first_season(self) -> int | None:
        return min(self.seasons) if self.seasons else None

    @property
    def last_season(self) -> int | None:
        return max(self.seasons) if self.seasons else None


@dataclass(frozen=True)
class Candidate:
    entity: Entity
    match: MatchKind
    # Raced (or hosted a race) in a season the question names.
    active: bool


@dataclass(frozen=True)
class Mention:
    """A name found in the question and the entities it may refer to."""

    text: str  # as written in the question
    alias: str  # normalised
    start: int  # character offsets in the question
    end: int
    candidates: tuple[Candidate, ...]

    @property
    def best(self) -> Candidate:
        return self.candidates[0]

    @property
    def ambiguous(self) -> bool:
        return len(self.candidates) > 1


@dataclass(frozen=True)
class Resolution:
    question: str
    seasons: tuple[int, ...]
    mentions: tuple[Mention, ...]

    def best(self, kind: EntityKind) -> list[Entity]:
        """The best candidate of each mention whose best guess is this kind."""
        return [m.best.entity for m in self.mentions if m.best.entity.kind == kind]


@dataclass(frozen=True)
class EntityIndex:
    """alias -> [(entity, match kind)]; immutable once built."""

    aliases: dict[str, tuple[tuple[Entity, MatchKind], ...]]
    max_words: int

    @classmethod
    def build(cls, entries: Iterable[tuple[str, Entity, MatchKind]]) -> "EntityIndex":
        grouped: dict[str, dict[tuple[str, int], tuple[Entity, MatchKind]]] = {}
        for alias, entity, match in entries:
            alias = normalise_alias(alias)
            if not alias:
                continue
            per_alias = grouped.setdefault(alias, {})
            key = (entity.kind, entity.id)
            known = per_alias.get(key)
            # One entity per alias, keeping its strongest match kind.
            if known is None or strength(entity.kind, match) > strength(
                entity.kind, known[1]
            ):
                per_alias[key] = (entity, match)
        aliases = {alias: tuple(found.values()) for alias, found in grouped.items()}
        max_words = max((alias.count(" ") + 1 for alias in aliases), default=1)
        return cls(aliases, max_words)

    def __len__(self) -> int:
        return len(self.aliases)


def circuit_aliases(ref: str, name: str, locality: str | None) -> set[str]:
    """Names a circuit goes by: its ref, locality, name, and the name without
    generic leading/trailing words ("Circuit de Spa-Francorchamps" -> "spa francorchamps").
    """
    found = {
        normalise_alias(ref.replace("_", " ").replace("-", " ")),
        normalise_alias(name),
    }
    if locality:
        found.add(normalise_alias(locality))
    words = normalise_alias(name).split()
    while len(words) > 1 and words[0] in _CIRCUIT_PREFIX:
        words.pop(0)
    while len(words) > 1 and words[-1] in _CIRCUIT_SUFFIX:
        words.pop()
    found.add(" ".join(words))
    return {alias for alias in found if alias}


def _rank(candidate: Candidate) -> tuple:
    e = candidate.entity
    return (
        not candidate.active,
        -strength(e.kind, candidate.match),
        -e.wins,
        -e.races,
        e.name,
        e.id,
    )


class EntityResolver:
    def __init__(
        self,
        load: Callable[[], EntityIndex],
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """`load` builds the index (load_entity_index with a session, or a fake)."""
        self._load = load
        self._ttl = ttl_seconds
        self._clock = clock
        self._index: EntityIndex | None = None
        self._loaded_at = 0.0
        self._lock = threading.Lock()

    def index(self) -> EntityIndex:
        with self._lock:
            stale = self._clock() - self._loaded_at > self._ttl
            if self._index is None or stale:
                try:
                    self._index = self._load()
                except SQLAlchemyError as exc:
                    logger.warning(
                        "Entity index failed to load: %s", type(exc).__name__
                    )
                    if self._index is None:  # nothing to fall back on
                        raise EntityIndexUnavailableError(
                            "Name lookup is unavailable right now"
                        ) from None
                    # Keep serving the previous index; retry after another TTL.
                self._loaded_at = self._clock()
            return self._index

    def resolve(self, question: str) -> Resolution:
        """Every driver, constructor and circuit named in the question, in order."""
        question = normalise_query(question)
        seasons = frozenset(filters_from_query(question).seasons)
        index = self.index()

        # (normalised token, start, end, capitalised) for each word.
        tokens: list[tuple[str, int, int, bool]] = []
        for word in _WORD.finditer(question):
            for token in normalise_alias(word.group()).split():
                tokens.append(
                    (token, word.start(), word.end(), word.group()[0].isupper())
                )

        mentions: list[Mention] = []
        i = 0
        while i < len(tokens):
            for length in range(min(index.max_words, len(tokens) - i), 0, -1):
                alias = " ".join(t[0] for t in tokens[i : i + length])
                found = index.aliases.get(alias)
                if not found or not self._allowed(alias, length, tokens[i][3]):
                    continue
                candidates = sorted(
                    (
                        Candidate(entity, match, bool(seasons & entity.seasons))
                        for entity, match in found
                    ),
                    key=_rank,
                )[:MAX_CANDIDATES]
                start, end = tokens[i][1], tokens[i + length - 1][2]
                mentions.append(
                    Mention(question[start:end], alias, start, end, tuple(candidates))
                )
                i += length
                break
            else:
                i += 1
        return Resolution(question, tuple(sorted(seasons)), tuple(mentions))

    @staticmethod
    def _allowed(alias: str, length: int, capitalised: bool) -> bool:
        if length > 1:
            return True
        if alias in NEVER_ALONE:
            return False
        return capitalised or alias not in COMMON_WORDS


_DRIVERS_SQL = text("""
SELECT d.driver_id AS id, d.ref, d.forename || ' ' || d.surname AS name,
       coalesce(s.seasons, '{}') AS seasons, coalesce(v.wins, 0) AS wins,
       coalesce(v.race_entries, 0) AS races
FROM drivers d
LEFT JOIN v_driver_career v USING (driver_id)
LEFT JOIN (
    SELECT r.driver_id, array_agg(DISTINCT ra.season) AS seasons
    FROM results r JOIN races ra USING (race_id) GROUP BY r.driver_id
) s USING (driver_id)
""")
_CONSTRUCTORS_SQL = text("""
SELECT c.constructor_id AS id, c.ref, c.name,
       coalesce(s.seasons, '{}') AS seasons, coalesce(s.wins, 0) AS wins,
       coalesce(s.races, 0) AS races
FROM constructors c
LEFT JOIN (
    SELECT r.constructor_id, array_agg(DISTINCT ra.season) AS seasons,
           count(DISTINCT r.race_id) FILTER (WHERE r.position = 1) AS wins,
           count(DISTINCT r.race_id) AS races
    FROM results r JOIN races ra USING (race_id) GROUP BY r.constructor_id
) s USING (constructor_id)
""")
_CIRCUITS_SQL = text("""
SELECT c.circuit_id AS id, c.ref, c.name, c.locality,
       coalesce(array_agg(DISTINCT ra.season) FILTER (WHERE ra.season IS NOT NULL), '{}')
           AS seasons,
       count(ra.race_id) AS races
FROM circuits c LEFT JOIN races ra USING (circuit_id)
GROUP BY c.circuit_id
""")


def load_entity_index(session: Session) -> EntityIndex:
    """Read the alias tables and circuits into an in-memory index (~90 ms on the
    full data). Only reads; the caller owns the session and its transaction."""
    drivers = {
        r.id: Entity(
            "driver", r.id, r.ref, r.name, frozenset(r.seasons), r.wins, r.races
        )
        for r in session.execute(_DRIVERS_SQL)
    }
    constructors = {
        r.id: Entity(
            "constructor", r.id, r.ref, r.name, frozenset(r.seasons), r.wins, r.races
        )
        for r in session.execute(_CONSTRUCTORS_SQL)
    }
    entries: list[tuple[str, Entity, MatchKind]] = []
    for r in session.execute(text("SELECT alias, driver_id, kind FROM driver_aliases")):
        if r.driver_id in drivers:
            entries.append((r.alias, drivers[r.driver_id], r.kind))
    for r in session.execute(
        text("SELECT alias, constructor_id, kind FROM constructor_aliases")
    ):
        if r.constructor_id in constructors:
            entries.append((r.alias, constructors[r.constructor_id], r.kind))

    circuits_by_ref: dict[str, Entity] = {}
    for r in session.execute(_CIRCUITS_SQL):
        circuit = Entity(
            "circuit", r.id, r.ref, r.name, frozenset(r.seasons), 0, r.races
        )
        circuits_by_ref[r.ref] = circuit
        entries.extend(
            (alias, circuit, "circuit")
            for alias in circuit_aliases(r.ref, r.name, r.locality)
        )
    for alias, ref in CIRCUIT_NICKNAMES.items():
        if ref in circuits_by_ref:
            entries.append((alias, circuits_by_ref[ref], "circuit"))
        else:
            logger.warning(
                "Circuit nickname %r points at unknown circuit %r", alias, ref
            )
    return EntityIndex.build(entries)


def _print_resolution(resolution: Resolution) -> None:
    seasons = ", ".join(map(str, resolution.seasons)) or "none"
    print(f"{len(resolution.mentions)} names found (seasons in question: {seasons})\n")
    for mention in resolution.mentions:
        print(f'"{mention.text}"' + ("  (ambiguous)" if mention.ambiguous else ""))
        for rank, c in enumerate(mention.candidates, start=1):
            e = c.entity
            years = f"{e.first_season}–{e.last_season}" if e.seasons else "no races"
            flags = f"{c.match}" + (", active" if c.active else "")
            record = (
                f"{e.races} races hosted"
                if e.kind == "circuit"
                else f"{e.wins} wins, {e.races} races"
            )
            print(
                f"  {rank}. {e.kind} {e.name} [{e.ref}, id {e.id}] "
                f"{years}, {record} ({flags})"
            )
        print()


def run(argv: list[str] | None = None) -> int:
    """`python -m app.retrieval.entities "question"`: show the names it finds."""
    import argparse
    import sys

    from app.core.config import get_settings
    from app.core.logging import configure_logging
    from app.db.session import create_db_engine

    parser = argparse.ArgumentParser(
        prog="python -m app.retrieval.entities",
        description="Find the drivers, constructors and circuits named in a question.",
    )
    parser.add_argument("question")
    args = parser.parse_args(argv)
    try:
        normalise_query(args.question)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_db_engine(settings)

    def load() -> EntityIndex:
        with Session(engine) as session:
            return load_entity_index(session)

    try:
        _print_resolution(EntityResolver(load).resolve(args.question))
    except SearchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
