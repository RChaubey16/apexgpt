"""Errors raised by knowledge search. Messages are safe to show to users."""


class SearchError(RuntimeError):
    """Search could not run (database or model failure). Never carries secrets."""


class EmbeddingUnavailableError(SearchError):
    """The query-embedding model could not be loaded or failed to embed."""
