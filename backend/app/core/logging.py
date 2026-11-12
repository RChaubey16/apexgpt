"""Basic logging setup. Structured file logging arrives in F4.5."""

import logging

_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def configure_logging(level: str) -> None:
    logging.basicConfig(level=level, format=_FORMAT, force=True)
