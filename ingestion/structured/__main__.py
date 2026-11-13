"""Load Jolpica-F1 structured data into Postgres.

    cd ingestion
    uv run python -m structured                     # download (cached) + load 1950-2025
    uv run python -m structured --dry-run           # transform only, print row counts
    uv run python -m structured --dump path/to.zip  # use a local dump file
    uv run python -m structured --first-season 2024 --last-season 2025

Needs DATABASE_URL (read from the environment or the repo's .env) and an
up-to-date schema (`cd backend && uv run alembic upgrade head`).
"""

import argparse
import logging
import sys
from pathlib import Path

import psycopg
from pydantic import ValidationError

from structured.config import Settings
from structured.download import download_dump, fetch_dump_info, sha256_of
from structured.dump import DumpReader
from structured.errors import IngestionError
from structured.load import connect, load
from structured.transform import FIRST_SEASON, transform

logger = logging.getLogger("structured")

DEFAULT_LAST_SEASON = 2025


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m structured", description="Load Jolpica-F1 data into Postgres."
    )
    parser.add_argument(
        "--dump", type=Path, help="local Jolpica CSV dump zip (skips download)"
    )
    parser.add_argument("--first-season", type=int, default=FIRST_SEASON)
    parser.add_argument("--last-season", type=int, default=DEFAULT_LAST_SEASON)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="transform and report counts; don't touch the DB",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    if not FIRST_SEASON <= args.first_season <= args.last_season <= 2100:
        parser.error(
            f"seasons must satisfy {FIRST_SEASON} <= --first-season <= --last-season <= 2100"
        )
    if args.dump is not None and not args.dump.is_file():
        parser.error(f"--dump: no such file: {args.dump}")
    return args


def run(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        settings = Settings()
    except ValidationError as exc:
        # Messages only (hide_input_in_errors keeps values out).
        for error in exc.errors():
            logger.error(
                "Invalid setting %s: %s", ".".join(map(str, error["loc"])), error["msg"]
            )
        return 2
    if not args.dry_run and settings.database_url is None:
        logger.error(
            "DATABASE_URL is not set (see .env.example); use --dry-run to skip the DB"
        )
        return 2

    try:
        if args.dump is not None:
            dump_path = args.dump
            logger.info(
                "Using local dump %s (sha256 %s)", dump_path, sha256_of(dump_path)[:16]
            )
        else:
            info = fetch_dump_info()
            dump_path = download_dump(info, settings.data_dir / "jolpica")

        with DumpReader(dump_path) as reader:
            data = transform(reader, args.first_season, args.last_season)
        if data.skipped_races:
            logger.info(
                "Skipped %d races without results (not run yet)", data.skipped_races
            )

        if args.dry_run:
            for table, count in data.counts().items():
                print(f"{table:<22} {count:>7}")
            return 0

        database_url = settings.database_url
        if database_url is None:  # already checked above; narrows the type
            return 2
        with connect(
            database_url.get_secret_value(), settings.database_connect_timeout
        ) as conn:
            load(conn, data, args.first_season, args.last_season)
    except IngestionError as exc:
        logger.error("%s", exc)
        return 1
    except psycopg.OperationalError as exc:
        # Connection problems: show the class and first line only (never the URL).
        logger.error(
            "Database connection failed: %s",
            str(exc).splitlines()[0] if str(exc) else type(exc).__name__,
        )
        return 1
    except psycopg.errors.UndefinedTable:
        logger.error(
            "F1 tables are missing: run `cd backend && uv run alembic upgrade head` first"
        )
        return 1
    except psycopg.Error as exc:
        logger.error("Load failed and was rolled back: %s: %s", type(exc).__name__, exc)
        return 1
    logger.info("Done")
    return 0


if __name__ == "__main__":
    sys.exit(run())
