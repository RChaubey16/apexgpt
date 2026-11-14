"""Errors the narrative pipeline reports to the user (no traceback)."""

from structured.errors import IngestionError


class WikiError(IngestionError):
    """A MediaWiki request failed or returned something unexpected."""


class SelectionError(IngestionError):
    """The article selection (topics.yaml, the structured data or a manifest) is wrong."""
