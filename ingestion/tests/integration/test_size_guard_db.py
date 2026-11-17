"""Size guard against a real Postgres (see test_load.py for setup notes).

The real budget is hundreds of MB; tests shrink the thresholds around the test
database's actual size instead.
"""

import logging
import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from common import size_guard
from common.size_guard import SizeGuard, SizeLimitError, database_size, table_sizes
from narrative import embed as embed_cli
from narrative.chunks import chunks_path, write_chunks
from narrative.embedder import MODEL_NAME
from narrative.store import plan_sync, sync_chunks
from structured import __main__ as load_cli
from structured.config import Settings, normalise_database_url
from structured.load import load
from structured.transform import transform
from tests.fixture_dump import FakeSource, write_zip
from tests.integration.test_chunks_store import FakeEmbedder, chunk
from tests.integration.test_load import F1_TABLES, migrated  # noqa: F401  (fixture)

pytestmark = pytest.mark.integration

_RAW_URL = os.environ.get("TEST_DATABASE_URL")
if not _RAW_URL:
    pytest.skip("TEST_DATABASE_URL not set", allow_module_level=True)
DATABASE_URL = normalise_database_url(_RAW_URL)


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute(f"TRUNCATE {', '.join(F1_TABLES)} RESTART IDENTITY CASCADE")
        connection.execute("TRUNCATE chunks")
        yield connection


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


def _rows(conn: psycopg.Connection, table: str) -> int:
    row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()  # noqa: S608
    return int(row[0]) if row else 0


def test_check_passes_under_the_limit(
    conn: psycopg.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    size = database_size(conn)

    assert SizeGuard(size + 1, size + 2).check(conn, "before loading") == size
    assert "warning level" not in caplog.text


def test_check_warns_past_the_warning_level(
    conn: psycopg.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    size = database_size(conn)

    SizeGuard(size // 2, size + 1).check(conn, "before loading")

    assert "past the" in caplog.text and "warning level" in caplog.text


def test_check_refuses_at_the_limit(conn: psycopg.Connection) -> None:
    size = database_size(conn)

    with pytest.raises(SizeLimitError, match=r"at or over the .* limit \(before x\)"):
        SizeGuard(size // 2, size).check(conn, "before x")


def test_report_lists_every_table_with_exact_counts(
    conn: psycopg.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    load(conn, transform(FakeSource()), 1950, 2025)

    tables = {t.name: t for t in table_sizes(conn)}
    assert set(tables) >= {*F1_TABLES, "chunks"}
    assert tables["results"].rows == _rows(conn, "results") > 0
    assert tables["chunks"].rows == 0
    assert tables["results"].total_bytes > tables["results"].index_bytes > 0
    sizes = [t.total_bytes for t in table_sizes(conn)]
    assert sizes == sorted(sizes, reverse=True)

    total = SizeGuard().report(conn)
    assert total == database_size(conn)
    assert "results" in caplog.text
    assert ": ok (warn 700.0 MB, limit 900.0 MB)" in caplog.text


def test_report_flags_a_database_over_the_limit(
    conn: psycopg.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    size = database_size(conn)

    SizeGuard(size // 2, size).report(conn)

    assert "OVER THE LIMIT" in caplog.text


def test_a_load_that_crosses_the_limit_rolls_back(conn: psycopg.Connection) -> None:
    before = database_size(conn)
    guard = SizeGuard(before + 1, before + 1)  # any growth crosses it

    with pytest.raises(SizeLimitError, match="after this load"):
        load(
            conn,
            transform(FakeSource()),
            1950,
            2025,
            before_commit=lambda c: guard.check(c, "after this load"),
        )

    assert all(_rows(conn, t) == 0 for t in F1_TABLES)


def test_the_chunk_sync_stops_at_the_limit(conn: psycopg.Connection) -> None:
    load(conn, transform(FakeSource()), 1950, 2025)
    chunks = [chunk(1, i, f"Paragraph {i}.") for i in range(4)]
    plan = plan_sync(conn, chunks, MODEL_NAME)
    calls: list[int] = []

    def guard(c: psycopg.Connection) -> None:
        calls.append(1)
        if len(calls) > 1:
            raise SizeLimitError("full")

    with pytest.raises(SizeLimitError):
        sync_chunks(conn, plan, FakeEmbedder(), batch_size=2, before_batch=guard)

    assert _rows(conn, "chunks") == 2  # the first batch is kept


def test_loader_cli_refuses_when_the_database_is_full(
    conn: psycopg.Connection,
    env: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    dump = write_zip(env / "dump.zip")
    monkeypatch.setattr(load_cli, "SizeGuard", lambda: SizeGuard(1, 1))

    assert load_cli.run(["--dump", str(dump), "--no-seeds", "--no-checks"]) == 1
    assert "refusing to load" in caplog.text
    assert "(before loading)" in caplog.text
    assert _rows(conn, "results") == 0


def test_loader_cli_reports_sizes_after_loading(
    conn: psycopg.Connection, env: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    dump = write_zip(env / "dump.zip")

    assert load_cli.run(["--dump", str(dump), "--no-seeds", "--no-checks"]) == 0
    assert "Database size" in caplog.text
    assert _rows(conn, "results") > 0


def test_embed_cli_refuses_when_the_database_is_full(
    conn: psycopg.Connection,
    env: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    write_chunks(chunks_path(env), [chunk(1, 0, "Lead.")])
    monkeypatch.setattr(embed_cli, "SizeGuard", lambda: SizeGuard(1, 1))
    monkeypatch.setattr(embed_cli, "_load_embedder", lambda s: FakeEmbedder())

    assert embed_cli.run([]) == 1
    assert "refusing to load" in caplog.text
    assert "(before syncing chunks)" in caplog.text  # before planning or embedding
    assert _rows(conn, "chunks") == 0


def test_embed_cli_reports_sizes_after_syncing(
    conn: psycopg.Connection,
    env: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    load(conn, transform(FakeSource()), 1950, 2025)
    write_chunks(chunks_path(env), [chunk(1, 0, "Lead.")])
    monkeypatch.setattr(embed_cli, "_load_embedder", lambda s: FakeEmbedder())

    assert embed_cli.run([]) == 0
    assert "Database size" in caplog.text
    assert "chunks" in caplog.text


@pytest.mark.parametrize(("refuse", "code"), [(10**12, 0), (1, 1)])
def test_standalone_cli_exits_1_at_or_over_the_limit(
    conn: psycopg.Connection,
    env: Path,
    monkeypatch: pytest.MonkeyPatch,
    refuse: int,
    code: int,
) -> None:
    monkeypatch.setattr(size_guard, "WARN_BYTES", 1)
    monkeypatch.setattr(size_guard, "REFUSE_BYTES", refuse)

    assert size_guard.run([]) == code
