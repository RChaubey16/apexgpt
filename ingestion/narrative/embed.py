"""Embed the chunks and sync them into Postgres (the `chunks` table).

    cd ingestion
    uv run python -m narrative.embed --dry-run   # what would change; no model, no writes
    uv run python -m narrative.embed             # embed new/changed chunks and sync

Reads data/narrative/chunks.jsonl (from `python -m narrative.chunk`). Needs
DATABASE_URL, the backend migrations, and the structured data loaded. The
model (bge-small-en-v1.5, ~65 MB) is downloaded once into data/models/.

Only chunks whose text changed are embedded (~10 chunks/s on a laptop CPU, so
~25 min for the whole corpus the first time, seconds after small changes).
Progress is committed in batches: an interrupted run resumes where it stopped.
"""

import argparse
import logging
import sys

import psycopg
from pydantic import ValidationError

from narrative.chunks import chunks_path, read_chunks
from narrative.embedder import MODEL_NAME, Embedder, FastEmbedder
from narrative.store import SyncPlan, plan_sync, sync_chunks
from structured.config import Settings
from structured.errors import IngestionError
from structured.load import connect

logger = logging.getLogger("narrative.embed")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m narrative.embed",
        description="Embed the narrative chunks and sync them into the database.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be embedded, written and deleted; change nothing",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def _load_embedder(settings: Settings) -> Embedder:
    """Overridden in tests."""
    return FastEmbedder(settings.data_dir / "models")


def _log_plan(plan: SyncPlan) -> None:
    logger.info(
        "%d chunks: %d unchanged, %d moved (embedding reused), %d to embed; "
        "%d stored chunks to delete",
        plan.total,
        len(plan.keep),
        len(plan.copy),
        len(plan.embed),
        len(plan.delete),
    )


def _progress(done: int, total: int, seconds: float) -> None:
    rate = done / seconds if seconds > 0 else 0.0
    left = (total - done) / rate if rate > 0 else 0.0
    logger.info(
        "  embedded %d/%d (%.1f/s, ~%d min left)", done, total, rate, round(left / 60)
    )


def run(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        settings = Settings()
    except ValidationError as exc:
        for error in exc.errors():
            logger.error(
                "Invalid setting %s: %s", ".".join(map(str, error["loc"])), error["msg"]
            )
        return 2
    if settings.database_url is None:
        logger.error("DATABASE_URL is not set (see .env.example)")
        return 2

    try:
        chunks = list(read_chunks(chunks_path(settings.data_dir)))
        if not chunks:
            logger.error("chunks.jsonl is empty; run `python -m narrative.chunk`")
            return 1
        with connect(
            settings.database_url.get_secret_value(), settings.database_connect_timeout
        ) as conn:
            conn.autocommit = True  # each batch commits on its own
            plan = plan_sync(conn, chunks, MODEL_NAME)
            _log_plan(plan)
            if args.dry_run:
                logger.info("--dry-run: nothing embedded or written")
                return 0
            embedder = _load_embedder(settings) if plan.embed else _NoEmbedder()
            report = sync_chunks(conn, plan, embedder, progress=_progress)
    except psycopg.Error as exc:
        # Never log the exception text: it can echo connection details.
        logger.error("Database error: %s", type(exc).__name__)
        return 1
    except IngestionError as exc:
        logger.error("%s", exc)
        return 1

    logger.info(
        "Synced %d chunks: %d embedded, %d moved, %d rows written, %d deleted; "
        "chunks table %.1f MB",
        report.chunks,
        report.embedded,
        report.copied,
        report.written,
        report.deleted,
        report.table_bytes / 1_000_000,
    )
    if report.truncated:
        logger.warning(
            "%d embedded chunks are longer than the model's 512 tokens "
            "(their ends are not embedded)",
            report.truncated,
        )
    return 0


class _NoEmbedder:
    """Used when nothing needs embedding, so the model isn't loaded."""

    model_name = MODEL_NAME
    dimensions = 384

    def embed(self, texts: object) -> list[list[float]]:
        raise AssertionError("nothing should be embedded")

    def truncated(self, texts: object) -> int:
        return 0


if __name__ == "__main__":
    sys.exit(run())
