"""Errors the loader reports to the user (the CLI prints them without a traceback)."""


class IngestionError(Exception):
    """Base class for expected, user-facing failures."""


class DownloadError(IngestionError):
    """The dump index or dump file could not be fetched or failed verification."""


class DumpError(IngestionError):
    """The dump is missing a file/column or holds a value we cannot load."""
