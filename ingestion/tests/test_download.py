import hashlib
import io
import json
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

from structured import download
from structured.download import (
    DumpInfo,
    cached_dump_path,
    download_dump,
    fetch_dump_info,
)
from structured.errors import DownloadError

PAYLOAD = b"fake zip bytes" * 100
PAYLOAD_HASH = hashlib.sha256(PAYLOAD).hexdigest()


def _index(**csv_overrides: Any) -> bytes:
    csv_dump = {
        "dump_type": "csv",
        "file_hash": PAYLOAD_HASH,
        "file_size": len(PAYLOAD),
        "uploaded_at": "2026-10-27T07:12:03Z",
        "download_url": "https://api.jolpi.ca/data/dumps/download/delayed/?dump_type=csv",
    }
    csv_dump.update(csv_overrides)
    return json.dumps(
        {
            "available_types": ["csv"],
            "delay_days": 14,
            "latest_dumps": {},
            "delayed_dumps": {"csv": csv_dump},
        }
    ).encode()


def _http_error(code: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = Message()
    if retry_after:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("https://x", code, "error", headers, None)


class FakeOpener:
    """Returns queued responses (bytes) or raises queued exceptions, in order."""

    def __init__(self, *responses: bytes | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[urllib.request.Request] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> io.BytesIO:
        assert timeout > 0
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return io.BytesIO(response)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    sleeps: list[float] = []
    monkeypatch.setattr(download.time, "sleep", sleeps.append)
    return sleeps


@pytest.fixture
def info() -> DumpInfo:
    return fetch_dump_info(FakeOpener(_index()))


# --- index ---


def test_fetch_dump_info(info: DumpInfo) -> None:
    assert info.file_hash == PAYLOAD_HASH
    assert info.file_size == len(PAYLOAD)


def test_requests_use_a_generic_user_agent() -> None:
    opener = FakeOpener(_index())
    fetch_dump_info(opener)

    assert opener.requests[0].get_header("User-agent") == download.USER_AGENT
    assert opener.requests[0].full_url == download.DUMPS_INDEX_URL


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"not json", "unexpected format"),
        (_index(file_hash="abc"), "unexpected format"),
        (_index(file_size=10**12), "unexpected format"),
        (_index(download_url="http://insecure.example/dump.zip"), "unexpected format"),
        (json.dumps({"delay_days": 14, "delayed_dumps": {}}).encode(), "no CSV dump"),
        (b"x" * (download.MAX_INDEX_BYTES + 1), "unexpectedly large"),
    ],
)
def test_bad_index_is_rejected(body: bytes, message: str) -> None:
    with pytest.raises(DownloadError, match=message):
        fetch_dump_info(FakeOpener(body))


# --- retries ---


def test_retries_server_errors_then_succeeds(no_sleep: list[float]) -> None:
    opener = FakeOpener(_http_error(503), _http_error(429, retry_after="7"), _index())

    fetch_dump_info(opener)

    assert len(opener.requests) == 3
    assert no_sleep == [2, 7]


def test_retry_after_is_capped(no_sleep: list[float]) -> None:
    fetch_dump_info(FakeOpener(_http_error(429, retry_after="3600"), _index()))

    assert no_sleep == [60]


def test_gives_up_after_max_attempts() -> None:
    opener = FakeOpener(*[_http_error(502)] * download.MAX_ATTEMPTS)

    with pytest.raises(DownloadError, match="HTTP 502 from api.jolpi.ca"):
        fetch_dump_info(opener)
    assert len(opener.requests) == download.MAX_ATTEMPTS


def test_client_errors_are_not_retried() -> None:
    opener = FakeOpener(_http_error(404))

    with pytest.raises(DownloadError, match="HTTP 404"):
        fetch_dump_info(opener)
    assert len(opener.requests) == 1


def test_network_errors_are_retried_and_reported_without_url() -> None:
    opener = FakeOpener(*[urllib.error.URLError("boom")] * download.MAX_ATTEMPTS)

    with pytest.raises(DownloadError, match="could not reach api.jolpi.ca: URLError"):
        fetch_dump_info(opener)


# --- download + cache ---


def test_download_verifies_and_caches(tmp_path: Path, info: DumpInfo) -> None:
    path = download_dump(info, tmp_path, FakeOpener(PAYLOAD))

    assert path == cached_dump_path(tmp_path, info)
    assert path.read_bytes() == PAYLOAD
    assert not list(tmp_path.glob("*.part"))


def test_cached_dump_is_reused_without_a_request(
    tmp_path: Path, info: DumpInfo
) -> None:
    download_dump(info, tmp_path, FakeOpener(PAYLOAD))
    opener = FakeOpener()

    download_dump(info, tmp_path, opener)

    assert opener.requests == []


def test_corrupt_cache_is_downloaded_again(tmp_path: Path, info: DumpInfo) -> None:
    cached_dump_path(tmp_path, info).write_bytes(b"corrupt")

    path = download_dump(info, tmp_path, FakeOpener(PAYLOAD))

    assert path.read_bytes() == PAYLOAD


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (PAYLOAD[:-1] + b"X", "SHA-256 does not match"),
        (PAYLOAD[:-10], "does not match the index"),
        (PAYLOAD + b"extra", "larger than the index says"),
    ],
)
def test_bad_download_is_not_cached(
    tmp_path: Path, info: DumpInfo, payload: bytes, message: str
) -> None:
    with pytest.raises(DownloadError, match=message):
        download_dump(info, tmp_path, FakeOpener(payload))

    assert list(tmp_path.iterdir()) == []


def test_non_https_urls_are_refused(info: DumpInfo, tmp_path: Path) -> None:
    opener = FakeOpener()
    insecure = info.model_copy(update={"download_url": "http://example.com/dump.zip"})

    with pytest.raises(DownloadError, match="non-https"):
        download_dump(insecure, tmp_path, opener)
    assert opener.requests == []
