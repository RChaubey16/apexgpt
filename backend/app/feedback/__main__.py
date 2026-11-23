"""Feedback maintenance from the command line.

    uv run python -m app.feedback purge   # delete feedback older than 90 days

Meant for a scheduled job (the weekly workflow, F7.3); saving feedback purges
too. Uses DATABASE_URL.
"""

import argparse
import sys

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import create_db_engine
from app.feedback.store import RETENTION_DAYS, purge_expired


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.feedback", description="Feedback maintenance."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "purge", help=f"delete feedback older than {RETENTION_DAYS} days"
    )
    parser.parse_args(argv)

    engine = create_db_engine(get_settings())
    try:
        with Session(engine) as session:
            purged = purge_expired(session)
            session.commit()
    except SQLAlchemyError as exc:
        # The error class only: driver messages can include host details.
        print(f"error: database unavailable ({type(exc).__name__})", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print(f"purged {purged} feedback rows older than {RETENTION_DAYS} days")
    return 0


if __name__ == "__main__":
    sys.exit(run())
