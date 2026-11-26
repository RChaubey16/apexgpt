"""python -m restore: copy the local data into Neon (see restore/__init__.py).

    TARGET_DATABASE_URL=postgresql://…?sslmode=require uv run python -m restore
    TARGET_DATABASE_URL=… uv run python -m restore --replace   # overwrite its data

The source is DATABASE_URL (the repo .env). The target URL comes from the
environment only, never the command line (which other users can see).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

import psycopg
from pydantic import ValidationError

from common.size_guard import REFUSE_BYTES, WARN_BYTES, SizeGuard
from restore import RestoreError, check_urls, restore
from structured.config import Settings, normalise_database_url
from structured.errors import IngestionError
from structured.load import connect

logger = logging.getLogger("restore")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m restore",
        description="Copy the data from DATABASE_URL into TARGET_DATABASE_URL.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="empty the target's data tables first (same transaction)",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        settings = Settings()
    except ValidationError:
        logger.error("Invalid settings in .env (DATABASE_URL?)")
        return 2
    if settings.database_url is None:
        logger.error("DATABASE_URL (the source) is not set")
        return 2
    raw_target = os.environ.get("TARGET_DATABASE_URL", "").strip()
    if not raw_target:
        logger.error("TARGET_DATABASE_URL is not set (the Neon connection string)")
        return 2
    try:
        target_url = normalise_database_url(raw_target)
    except ValueError as exc:
        logger.error("TARGET_%s", exc)
        return 2
    source_url = settings.database_url.get_secret_value()
    try:
        check_urls(source_url, target_url)
    except RestoreError as exc:
        logger.error("%s", exc)
        return 2

    guard = SizeGuard(WARN_BYTES, REFUSE_BYTES)
    timeout = settings.database_connect_timeout
    try:
        with connect(source_url, timeout) as source, connect(
            target_url, timeout
        ) as target:
            result = restore(source, target, replace=args.replace, guard=guard)
            logger.info(
                "Restored %d tables, %s rows; %d sequences; %d sanity checks passed",
                len(result.tables),
                f"{sum(t.rows for t in result.tables):,}",
                result.sequences,
                result.checks_passed,
            )
            guard.report(target)
    except IngestionError as exc:  # RestoreError, SizeLimitError: rolled back
        logger.error("Restore failed, nothing was changed: %s", exc)
        return 1
    except psycopg.Error as exc:
        # Never log the exception text: it can echo connection details.
        logger.error("Database error, nothing was changed: %s", type(exc).__name__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
