"""Pipeline files in data/narrative/: one pydantic model per line, written atomically."""

import json
import os
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path

from pydantic import BaseModel, ValidationError

from narrative.errors import SelectionError

MAX_LINE_BYTES = 5_000_000


def write_jsonl(path: Path, records: Iterable[BaseModel]) -> int:
    """Replace `path` with the records; an interrupted run keeps the old file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".jsonl")
    count = 0
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for record in records:
                f.write(record.model_dump_json(exclude_defaults=True))
                f.write("\n")
                count += 1
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return count


def read_jsonl[M: BaseModel](path: Path, model: type[M], command: str) -> Iterator[M]:
    """Validate each line; `command` is what writes the file, for the error."""
    if not path.is_file():
        raise SelectionError(f"no {path.name} at {path}; run `{command}` first")
    with path.open(encoding="utf-8") as f:
        for number, line in enumerate(f, start=1):
            if len(line) > MAX_LINE_BYTES:
                raise SelectionError(f"{path.name} line {number} is unexpectedly large")
            try:
                yield model.model_validate(json.loads(line))
            except (ValueError, ValidationError):
                raise SelectionError(
                    f"{path.name} line {number} is unreadable; run `{command}` again"
                ) from None
