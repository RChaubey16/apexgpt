"""Read and validate the curated title overrides (narrative/title_overrides.csv).

Some Wikipedia URLs in the structured data have gone stale: the page they name
became a disambiguation page ("Tony Brooks") or was renamed. An override gives
the article title to use instead, keyed by the entity's `ref`:

    kind,ref,title
    driver,brooks,Tony Brooks (racing driver)

`kind` is driver, constructor or circuit. Lines starting with # are comments.
Refs are checked against the database when the selection is built; titles must
resolve to a real article when it's resolved.
"""

import csv
import io
from pathlib import Path

from narrative.errors import SelectionError
from narrative.selection import OVERRIDABLE_KINDS, Kind, TitleOverride
from narrative.wiki import validate_title

OVERRIDES_FILE = Path(__file__).resolve().parent / "title_overrides.csv"
MAX_FILE_BYTES = 1_000_000
_COLUMNS = ["kind", "ref", "title"]


def parse_overrides(
    text: str, source: str = "title_overrides.csv"
) -> list[TitleOverride]:
    lines = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    reader = csv.DictReader(io.StringIO("\n".join(lines)), strict=True)
    try:
        rows = list(reader)
    except csv.Error as exc:
        raise SelectionError(f"{source} is not valid CSV: {exc}") from None
    if reader.fieldnames != _COLUMNS:
        raise SelectionError(f"{source}: the header must be {','.join(_COLUMNS)}")

    problems: list[str] = []
    overrides: list[TitleOverride] = []
    seen: set[tuple[str, str]] = set()
    for number, row in enumerate(rows, start=2):
        where = f"row {number}"
        if None in row or any(v is None for v in row.values()):
            problems.append(f"{where}: expected 3 columns")
            continue
        kind, ref, title = (row[c].strip() for c in _COLUMNS)
        if kind not in {k.value for k in OVERRIDABLE_KINDS}:
            allowed = ", ".join(k.value for k in OVERRIDABLE_KINDS)
            problems.append(f"{where}: kind must be one of {allowed} (got {kind!r})")
            continue
        if not ref:
            problems.append(f"{where}: ref is empty")
            continue
        try:
            title = validate_title(title)
        except ValueError as exc:
            problems.append(f"{where}: {exc}")
            continue
        if (kind, ref) in seen:
            problems.append(f"{where}: {kind} {ref!r} is listed twice")
            continue
        seen.add((kind, ref))
        overrides.append(TitleOverride(Kind(kind), ref, title))
    if problems:
        raise SelectionError(f"{source} is invalid:\n  " + "\n  ".join(problems))
    return overrides


def read_overrides(path: Path = OVERRIDES_FILE) -> list[TitleOverride]:
    try:
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise SelectionError(f"{path.name} is unexpectedly large ({size} bytes)")
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SelectionError(
            f"cannot read {path.name}: {exc.strerror or type(exc).__name__}"
        ) from None
    return parse_overrides(text, path.name)
