"""Logging (F4.5): readable lines on the console, JSON lines in rotated files.

    configure_logging("INFO", log_file=Path("/app/logs/apexgpt.log"))
    logger.info("Chat answered", extra={"event": "chat", "latency_ms": 812})

- Console (stderr): `time LEVEL [logger] message`, as before.
- File (when LOG_FILE is set): one JSON object per line with `ts` (UTC),
  `level`, `logger`, `message`, any `extra` fields, and `error` / `traceback`
  for exceptions. Rotated by size (LOG_FILE_MAX_MB × LOG_FILE_BACKUPS), so the
  disk use is bounded. Not the database: logs must not wake Neon.
- Only the handlers installed here are replaced on a second call; handlers
  added by others (pytest's log capture, uvicorn's own loggers) are kept.
- If the file can't be opened, a warning goes to the console and the app runs
  on: losing logs must not take the API down.

Events written by the API (`extra={"event": ...}`): `chat` (one per request:
question, tools, provider, latency, tokens, cache, outcome), `feedback`, and
`rate_limited`. No IP addresses or other client identifiers are logged here;
uvicorn's access log (console only) doesn't reach the file.
"""

import json
import logging
import logging.handlers
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_OURS = "_apexgpt_handler"
# LogRecord's own attributes; everything else on a record came from `extra`.
_STANDARD = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}

logger = logging.getLogger(__name__)


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return repr(value)
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD and not key.startswith("_") and key not in entry:
                entry[key] = _json_safe(value)
        if record.exc_info and record.exc_info[0] is not None:
            entry["error"] = record.exc_info[0].__name__
            entry["traceback"] = "".join(traceback.format_exception(*record.exc_info))
        return json.dumps(entry, ensure_ascii=False)


def _mark(handler: logging.Handler) -> logging.Handler:
    setattr(handler, _OURS, True)
    return handler


def configure_logging(
    level: str,
    *,
    log_file: Path | None = None,
    max_bytes: int = 10 * 1024 * 1024,
    backups: int = 5,
) -> None:
    root = logging.getLogger()
    for handler in [h for h in root.handlers if getattr(h, _OURS, False)]:
        root.removeHandler(handler)
        handler.close()
    root.setLevel(level)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(_mark(console))

    if log_file is None:
        return
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
        )
    except OSError as exc:
        logger.warning(
            "Log file %s can't be opened (%s); logging to the console only",
            log_file,
            type(exc).__name__,
        )
        return
    file_handler.setFormatter(JsonFormatter())
    root.addHandler(_mark(file_handler))
