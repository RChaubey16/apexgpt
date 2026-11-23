"""Per-IP rate limits (F4.4), with the `limits` library (slowapi's engine).

    @router.post("/chat", dependencies=[Depends(rate_limit("chat"))])

Each app holds its own limiter (`app.state.rate_limiter`), built from settings
(`RATE_LIMIT_CHAT`, `RATE_LIMIT_FEEDBACK`, e.g. "6/minute;100/day"; blank = no
limit), so tests and apps never share counters.

- Moving windows in memory: one uvicorn worker, so no shared store is needed.
  A restart resets the counts.
- The key is `request.client.host`. Behind the proxy, uvicorn sets it from
  X-Forwarded-For only for the proxies in FORWARDED_ALLOW_IPS; the header is
  never read here, so a client can't choose its own key.
- Over a limit: 429 `{"detail": ...}` with `Retry-After`, before the endpoint
  runs (so no LLM tokens or database work are spent).
"""

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import HTTPException, Request, status
from limits import RateLimitItem, parse_many
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter

logger = logging.getLogger(__name__)

UNKNOWN_CLIENT = "unknown"


def parse_limits(spec: str) -> tuple[RateLimitItem, ...]:
    """'6/minute;100/day' → limit items; blank → none. Raises ValueError."""
    spec = spec.strip()
    if not spec:
        return ()
    try:
        items = tuple(parse_many(spec))
    except ValueError:
        raise ValueError(
            f"invalid rate limit {spec!r}; use e.g. '6/minute;100/day'"
        ) from None
    if any(item.amount < 1 for item in items):
        raise ValueError(f"invalid rate limit {spec!r}: amounts must be at least 1")
    return items


@dataclass(frozen=True)
class Rejection:
    limit: str  # e.g. "6 per 1 minute"
    retry_after: int  # seconds


class RateLimiter:
    def __init__(self, limits: dict[str, tuple[RateLimitItem, ...]]) -> None:
        self._limits = limits
        self._limiter = MovingWindowRateLimiter(MemoryStorage())

    def hit(self, scope: str, key: str) -> Rejection | None:
        """Count one request; a Rejection if it is over any of the scope's limits."""
        for item in self._limits.get(scope, ()):
            if not self._limiter.hit(item, scope, key):
                reset = self._limiter.get_window_stats(item, scope, key).reset_time
                return Rejection(str(item), max(1, math.ceil(reset - time.time())))
        return None

    def reset(self) -> None:
        self._limiter.storage.reset()


def client_key(request: Request) -> str:
    return request.client.host if request.client else UNKNOWN_CLIENT


def rate_limit(scope: str) -> Callable[[Request], None]:
    """A dependency that counts the request against `scope`'s limits."""

    def check(request: Request) -> None:
        limiter: RateLimiter = request.app.state.rate_limiter
        rejection = limiter.hit(scope, client_key(request))
        if rejection is not None:
            # No client address in the log: rate limits are about volume.
            logger.warning("Rate limited: %s (%s)", scope, rejection.limit)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    "Too many requests; please try again in "
                    f"{rejection.retry_after} seconds"
                ),
                headers={"Retry-After": str(rejection.retry_after)},
            )

    return check
