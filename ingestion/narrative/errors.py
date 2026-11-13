"""Errors the narrative pipeline reports to the user (no traceback)."""

from structured.errors import IngestionError


class WikiError(IngestionError):
    """A MediaWiki request failed or returned something unexpected."""
