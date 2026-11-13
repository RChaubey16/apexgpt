"""Entity aliases and constructor lineage: generated names plus curated seeds.

Synced inside the loader's transaction, after drivers and constructors are
upserted, against every entity in the database (not just the loaded seasons):

- driver_aliases: full name ("name") and surname ("surname") of every driver,
  plus curated nicknames from seeds/driver_aliases.csv ("nickname").
- constructor_aliases: name and ref ("red_bull" -> "red bull") of every
  constructor ("name"), plus curated nicknames from seeds/constructor_aliases.csv.
- constructor_lineage: seeds/constructor_lineage.csv, checked against the race
  data (the successor raced in `season`; the predecessor in that season or the
  one before), so a wrong year or ref fails the load.

Seeds use stable `ref` slugs, never numeric IDs. An alias may map to several
entities ("schumacher", "kimi"); choosing between them is entity resolution's
job (F3.4). Every table is fully synced: rows no longer generated or seeded are
deleted, so editing a seed file and re-running the loader is enough.
"""

import csv
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import psycopg
from psycopg import sql

from structured.errors import SeedError
from structured.report import TableReport

SEEDS_DIR = Path(__file__).parent / "seeds"

# Letters NFKD does not decompose into ASCII + combining marks.
_TRANSLITERATE = str.maketrans(
    {"ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae", "œ": "oe", "Œ": "oe", "ß": "ss",
     "ł": "l", "Ł": "l", "đ": "d", "Đ": "d", "ð": "d", "þ": "th", "ı": "i"}
)  # fmt: skip
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_REF = re.compile(r"^[a-z0-9_-]+$")


def normalise_alias(text: str) -> str:
    """'Sergio Pérez' -> 'sergio perez'; "O'Ward" -> 'o ward'; 'Räikkönen' -> 'raikkonen'.

    Must match the format check on the alias tables: lowercase ASCII letters and
    digits separated by single spaces. Lookups (F3.4) must use the same function.
    """
    decomposed = unicodedata.normalize("NFKD", text.translate(_TRANSLITERATE))
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _NON_ALNUM.sub(" ", ascii_only.lower()).strip()


@dataclass(frozen=True)
class LineageSeed:
    predecessor: str
    successor: str
    season: int
    note: str | None


@dataclass
class Seeds:
    driver_aliases: list[tuple[str, str]] = field(default_factory=list)
    constructor_aliases: list[tuple[str, str]] = field(default_factory=list)
    lineage: list[LineageSeed] = field(default_factory=list)


def _read_csv(path: Path, columns: tuple[str, ...]) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if tuple(reader.fieldnames or ()) != columns:
                raise SeedError(f"{path.name}: header must be {','.join(columns)}")
            rows = list(reader)
    except OSError as exc:
        raise SeedError(f"cannot read seed file {path.name}: {exc}") from None
    for line, row in enumerate(rows, start=2):
        if any(row[c] is None for c in columns) or None in row:
            raise SeedError(f"{path.name}:{line}: expected {len(columns)} columns")
    return rows


def _alias_seeds(path: Path) -> list[tuple[str, str]]:
    seeds = []
    seen = set()
    for line, row in enumerate(_read_csv(path, ("ref", "alias")), start=2):
        ref, alias = row["ref"].strip(), normalise_alias(row["alias"])
        if not _REF.match(ref):
            raise SeedError(f"{path.name}:{line}: invalid ref {row['ref']!r}")
        if not alias:
            raise SeedError(f"{path.name}:{line}: alias {row['alias']!r} is empty")
        if (ref, alias) in seen:
            raise SeedError(f"{path.name}:{line}: duplicate alias {alias!r} for {ref}")
        seen.add((ref, alias))
        seeds.append((ref, alias))
    return seeds


def _lineage_seeds(path: Path) -> list[LineageSeed]:
    columns = ("predecessor", "successor", "season", "note")
    seeds = []
    seen = set()
    for line, row in enumerate(_read_csv(path, columns), start=2):
        pred, succ = row["predecessor"].strip(), row["successor"].strip()
        if not (_REF.match(pred) and _REF.match(succ)) or pred == succ:
            raise SeedError(f"{path.name}:{line}: invalid predecessor/successor")
        try:
            season = int(row["season"])
        except ValueError:
            raise SeedError(f"{path.name}:{line}: season is not a year") from None
        if not 1950 <= season <= 2100:
            raise SeedError(f"{path.name}:{line}: season {season} is out of range")
        if (pred, succ, season) in seen:
            raise SeedError(f"{path.name}:{line}: duplicate lineage row")
        seen.add((pred, succ, season))
        seeds.append(LineageSeed(pred, succ, season, row["note"].strip() or None))
    return seeds


def read_seeds(directory: Path = SEEDS_DIR) -> Seeds:
    return Seeds(
        driver_aliases=_alias_seeds(directory / "driver_aliases.csv"),
        constructor_aliases=_alias_seeds(directory / "constructor_aliases.csv"),
        lineage=_lineage_seeds(directory / "constructor_lineage.csv"),
    )


# --- sync ---

AliasRow = tuple[str, int, str]  # (alias, entity id, kind)


def _resolve(
    refs: dict[str, int], ref: str, what: str, unknown: set[str]
) -> int | None:
    if ref not in refs:
        unknown.add(f"{what} {ref!r}")
        return None
    return refs[ref]


def _dedupe(rows: Iterable[AliasRow]) -> dict[tuple[str, int], str]:
    """(alias, id) -> kind; the first kind wins (generated before curated)."""
    out: dict[tuple[str, int], str] = {}
    for alias, entity_id, kind in rows:
        if alias:
            out.setdefault((alias, entity_id), kind)
    return out


def _sync_aliases(
    cur: psycopg.Cursor, table: str, id_column: str, desired: dict[tuple[str, int], str]
) -> TableReport:
    names = {"t": sql.Identifier(table), "id": sql.Identifier(id_column)}
    cur.execute(sql.SQL("SELECT alias, {id}, kind FROM {t}").format(**names))
    existing = {(alias, entity_id): kind for alias, entity_id, kind in cur.fetchall()}
    stale = [key for key in existing if key not in desired]
    new = [(*key, kind) for key, kind in desired.items() if key not in existing]
    changed = [
        (kind, *key)
        for key, kind in desired.items()
        if key in existing and existing[key] != kind
    ]
    cur.executemany(
        sql.SQL("DELETE FROM {t} WHERE alias = %s AND {id} = %s").format(**names), stale
    )
    cur.executemany(
        sql.SQL("INSERT INTO {t} (alias, {id}, kind) VALUES (%s, %s, %s)").format(
            **names
        ),
        new,
    )
    cur.executemany(
        sql.SQL("UPDATE {t} SET kind = %s WHERE alias = %s AND {id} = %s").format(
            **names
        ),
        changed,
    )
    return TableReport(inserted=len(new), updated=len(changed), deleted=len(stale))


def _seasons_raced(cur: psycopg.Cursor) -> dict[int, set[int]]:
    cur.execute(
        "SELECT DISTINCT res.constructor_id, r.season "
        "FROM results res JOIN races r USING (race_id)"
    )
    raced: dict[int, set[int]] = {}
    for constructor_id, season in cur.fetchall():
        raced.setdefault(constructor_id, set()).add(season)
    return raced


def _sync_lineage(
    cur: psycopg.Cursor, seeds: list[LineageSeed], refs: dict[str, int]
) -> TableReport:
    unknown: set[str] = set()
    raced = _seasons_raced(cur)
    desired: dict[tuple[int, int, int], str | None] = {}
    problems = []
    for seed in seeds:
        pred = _resolve(refs, seed.predecessor, "constructor", unknown)
        succ = _resolve(refs, seed.successor, "constructor", unknown)
        if pred is None or succ is None:
            continue
        label = f"{seed.predecessor} -> {seed.successor} ({seed.season})"
        if seed.season not in raced.get(succ, set()):
            problems.append(f"{label}: {seed.successor} did not race in {seed.season}")
        if not {seed.season - 1, seed.season} & raced.get(pred, set()):
            problems.append(
                f"{label}: {seed.predecessor} did not race in {seed.season - 1} or {seed.season}"
            )
        desired[(pred, succ, seed.season)] = seed.note
    if unknown:
        raise SeedError(
            f"constructor_lineage.csv: unknown {', '.join(sorted(unknown))}"
        )
    if problems:
        raise SeedError(
            "constructor_lineage.csv does not match the race data: "
            + "; ".join(problems)
        )

    cur.execute(
        "SELECT predecessor_id, successor_id, season, note FROM constructor_lineage"
    )
    existing = {(p, s, y): note for p, s, y, note in cur.fetchall()}
    stale = [key for key in existing if key not in desired]
    new = [(*key, note) for key, note in desired.items() if key not in existing]
    changed = [
        (note, *key)
        for key, note in desired.items()
        if key in existing and existing[key] != note
    ]
    cur.executemany(
        "DELETE FROM constructor_lineage "
        "WHERE predecessor_id = %s AND successor_id = %s AND season = %s",
        stale,
    )
    cur.executemany(
        "INSERT INTO constructor_lineage (predecessor_id, successor_id, season, note) "
        "VALUES (%s, %s, %s, %s)",
        new,
    )
    cur.executemany(
        "UPDATE constructor_lineage SET note = %s "
        "WHERE predecessor_id = %s AND successor_id = %s AND season = %s",
        changed,
    )
    return TableReport(inserted=len(new), updated=len(changed), deleted=len(stale))


def sync_seeds(cur: psycopg.Cursor, seeds: Seeds) -> dict[str, TableReport]:
    """Sync aliases and lineage with the drivers/constructors in the database."""
    cur.execute("SELECT driver_id, ref, forename, surname FROM drivers")
    drivers = cur.fetchall()
    cur.execute("SELECT constructor_id, ref, name FROM constructors")
    constructors = cur.fetchall()
    driver_refs = {ref: driver_id for driver_id, ref, _, _ in drivers}
    constructor_refs = {ref: cid for cid, ref, _ in constructors}

    unknown: set[str] = set()
    driver_rows: list[AliasRow] = []
    for driver_id, _, forename, surname in drivers:
        driver_rows.append(
            (normalise_alias(f"{forename} {surname}"), driver_id, "name")
        )
        driver_rows.append((normalise_alias(surname), driver_id, "surname"))
    for ref, alias in seeds.driver_aliases:
        driver_id = _resolve(driver_refs, ref, "driver", unknown)
        if driver_id is not None:
            driver_rows.append((alias, driver_id, "nickname"))

    constructor_rows: list[AliasRow] = []
    for cid, ref, name in constructors:
        constructor_rows.append((normalise_alias(name), cid, "name"))
        constructor_rows.append((normalise_alias(ref), cid, "name"))
    for ref, alias in seeds.constructor_aliases:
        cid = _resolve(constructor_refs, ref, "constructor", unknown)
        if cid is not None:
            constructor_rows.append((alias, cid, "nickname"))

    if unknown:
        raise SeedError(
            f"alias seeds reference unknown {', '.join(sorted(unknown))} "
            "(load the full season range first, or pass --no-seeds)"
        )
    return {
        "driver_aliases": _sync_aliases(
            cur, "driver_aliases", "driver_id", _dedupe(driver_rows)
        ),
        "constructor_aliases": _sync_aliases(
            cur, "constructor_aliases", "constructor_id", _dedupe(constructor_rows)
        ),
        "constructor_lineage": _sync_lineage(cur, seeds.lineage, constructor_refs),
    }
