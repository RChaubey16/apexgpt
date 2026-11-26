"""Query embeddings: bge-small-en-v1.5 via fastembed (ONNX, CPU).

Chunks were embedded by the ingestion pipeline with the same model
(ingestion/narrative/embedder.py, MODEL_NAME), as passages. Questions are
embedded with bge's retrieval instruction in front, which the model card
recommends for short queries; on our labelled queries it ranked the expected
articles higher than the bare question (see docs/archive/v1.0.0-mvp/PROGRESS.md, F3.1).
"""

import logging
import math
import threading
from pathlib import Path
from typing import Any, Protocol

from app.retrieval.errors import EmbeddingUnavailableError

logger = logging.getLogger(__name__)

# Must match ingestion/narrative/embedder.py (a test checks it).
MODEL_NAME = "BAAI/bge-small-en-v1.5"
DIMENSIONS = 384
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


class QueryEmbedder(Protocol):
    def embed_query(self, query: str) -> list[float]:
        """A normalised vector of DIMENSIONS floats for one search query."""
        ...


class FastEmbedQueryEmbedder:
    """Loads the model on first use (~1–2 s, ~65 MB download the first time).

    Loading is lazy so the API starts without it, and guarded by a lock so
    concurrent first requests load it once.
    """

    def __init__(self, cache_dir: Path | None = None, threads: int = 1) -> None:
        self._cache_dir = cache_dir
        self._threads = threads  # see Settings.onnx_threads
        self._model: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        with self._lock:
            if self._model is None:
                try:
                    from fastembed import TextEmbedding  # slow import

                    cache = str(self._cache_dir) if self._cache_dir else None
                    self._model = TextEmbedding(
                        MODEL_NAME, cache_dir=cache, threads=self._threads
                    )
                except Exception as exc:  # download, disk or ONNX runtime errors
                    logger.warning(
                        "Embedding model failed to load: %s", type(exc).__name__
                    )
                    raise EmbeddingUnavailableError(
                        "The search model could not be loaded"
                    ) from None
                logger.info("Loaded embedding model %s", MODEL_NAME)
            return self._model

    def embed_query(self, query: str) -> list[float]:
        model = self._load()
        try:
            vectors = list(model.query_embed([QUERY_INSTRUCTION + query]))
        except Exception as exc:
            logger.warning("Query embedding failed: %s", type(exc).__name__)
            raise EmbeddingUnavailableError(
                "The question could not be embedded"
            ) from None
        return validate_vector(vectors[0].tolist() if vectors else [])


def validate_vector(vector: list[float]) -> list[float]:
    """Reject vectors the database would refuse or that would rank nonsense."""
    if len(vector) != DIMENSIONS or not all(math.isfinite(x) for x in vector):
        raise EmbeddingUnavailableError("The search model returned an invalid vector")
    return vector
