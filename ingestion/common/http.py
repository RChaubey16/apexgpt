"""Small HTTP helper shared by the fetchers (stdlib only).

https only, a caller-supplied User-Agent, a timeout, and retries on network
errors, 429 and 5xx (honouring Retry-After, capped). Error messages and logs
name the host only: some URLs (signed S3 links) carry credentials in the query.
"""

import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import IO

logger = logging.getLogger(__name__)

Opener = Callable[..., IO[bytes]]

DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_ATTEMPTS = 3
MAX_RETRY_AFTER_SECONDS = 60


def host(url: str) -> str:
    return urllib.parse.urlsplit(url).netloc


def retry_after(headers: object) -> int | None:
    """Seconds from a Retry-After header (capped), or None."""
    value = headers.get("Retry-After") if headers is not None else None  # type: ignore[attr-defined]
    if isinstance(value, str) and value.isdigit():
        return min(int(value), MAX_RETRY_AFTER_SECONDS)
    return None


def open_url(
    url: str,
    opener: Opener,
    *,
    user_agent: str,
    error: type[Exception],
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    attempts: int = DEFAULT_ATTEMPTS,
) -> IO[bytes]:
    """Open an https URL, retrying network errors, 429 and 5xx responses.

    Raises `error` (the caller's exception type) when the request can't succeed.
    """
    if urllib.parse.urlsplit(url).scheme != "https":
        raise error("refusing to fetch a non-https URL")
    request = urllib.request.Request(  # noqa: S310 (https enforced above)
        url, headers={"User-Agent": user_agent}
    )
    for attempt in range(1, attempts + 1):
        try:
            return opener(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            retryable = exc.code == 429 or exc.code >= 500
            if not retryable or attempt == attempts:
                raise error(f"HTTP {exc.code} from {host(url)}") from None
            delay = retry_after(exc.headers) or 2**attempt
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            if attempt == attempts:
                raise error(
                    f"could not reach {host(url)}: {type(exc).__name__}"
                ) from None
            delay = 2**attempt
        logger.warning("Request to %s failed; retrying in %ss", host(url), delay)
        time.sleep(delay)
    raise AssertionError("unreachable")
