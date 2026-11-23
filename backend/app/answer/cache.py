"""In-memory LRU cache of complete answers (F4.4).

    cache = AnswerCache(size=256, ttl_seconds=86_400)
    events = cache.get(cache_key(question))   # the recorded events, or None
    cache.put(cache_key(question), events)

The orchestrator records the events of an answer (tool, table, token,
citation, done) and replays them for the same question; a replay spends no
LLM tokens and runs no tools. The data covers finished seasons (1950–2025), so
a day-long TTL loses little; a data reload is seen once entries expire (or on
restart).

- Keyed by the standalone question (after a follow-up is condensed), folded:
  case, Unicode compatibility forms, whitespace and trailing punctuation.
- Only answers worth repeating are stored (the orchestrator decides: every
  tool available and every call succeeded).
- Thread-safe (answers stream in worker threads), bounded by entry count.
"""

import re
import threading
import time
import unicodedata
from collections import OrderedDict
from collections.abc import Callable, Sequence
from typing import Any

_SPACES = re.compile(r"\s+")
_TRAILING = re.compile(r"[\s?!.。？！]+$")


def cache_key(question: str) -> str:
    text = unicodedata.normalize("NFKC", question).casefold()
    return _TRAILING.sub("", _SPACES.sub(" ", text).strip())


def coalesce(events: Sequence[Any], token_type: type) -> tuple[Any, ...]:
    """Merge runs of token events into one (smaller to keep, faster to replay)."""
    out: list[Any] = []
    for event in events:
        if out and isinstance(event, token_type) and isinstance(out[-1], token_type):
            out[-1] = token_type(out[-1].text + event.text)
        else:
            out.append(event)
    return tuple(out)


class AnswerCache:
    def __init__(
        self,
        size: int,
        ttl_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if size < 1:
            raise ValueError("cache size must be at least 1")
        self._size = size
        self._ttl = ttl_seconds
        self._clock = clock
        self._entries: OrderedDict[str, tuple[float, tuple[Any, ...]]] = OrderedDict()
        self._lock = threading.Lock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def get(self, key: str) -> tuple[Any, ...] | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            stored_at, events = entry
            if self._clock() - stored_at >= self._ttl:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return events

    def put(self, key: str, events: tuple[Any, ...]) -> None:
        with self._lock:
            self._entries[key] = (self._clock(), events)
            self._entries.move_to_end(key)
            while len(self._entries) > self._size:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
