"""Cross-encoder reranking: Xenova/ms-marco-MiniLM-L-6-v2 via fastembed (ONNX, CPU).

The plan named BAAI/bge-reranker-base. Measured on the labelled questions, it
took ~1.6 s per question, peaked at ~2 GB of RAM (the backend's limit is 768 MB)
and failed the Senna/Suzuka acceptance test. MiniLM-L-6 (80 MB) passed every
question in the top 5 at ~0.2 s and adds ~170 MB (docs/archive/v1.0.0-mvp/PROGRESS.md, F3.2).

Documents are scored one at a time (batch size 1): with batches, ONNX Runtime
holds activations for several 512-token inputs at once, which raised peak
memory from ~430 MB to ~670 MB for no gain in speed on CPU.
"""

import logging
import math
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

from app.retrieval.errors import RerankerUnavailableError

logger = logging.getLogger(__name__)

MODEL_NAME = "Xenova/ms-marco-MiniLM-L-6-v2"
BATCH_SIZE = 1


class Reranker(Protocol):
    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        """One relevance score per document (higher is more relevant), in order."""
        ...


class FastEmbedReranker:
    """Loads the model on first use (80 MB download the first time), once, under a lock."""

    def __init__(self, cache_dir: Path | None = None, threads: int = 1) -> None:
        self._cache_dir = cache_dir
        self._threads = threads  # see Settings.onnx_threads
        self._model: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        with self._lock:
            if self._model is None:
                try:
                    from fastembed.rerank.cross_encoder import TextCrossEncoder

                    cache = str(self._cache_dir) if self._cache_dir else None
                    self._model = TextCrossEncoder(
                        MODEL_NAME, cache_dir=cache, threads=self._threads
                    )
                except Exception as exc:  # download, disk or ONNX runtime errors
                    logger.warning(
                        "Reranker model failed to load: %s", type(exc).__name__
                    )
                    raise RerankerUnavailableError(
                        "The reranking model could not be loaded"
                    ) from None
                logger.info("Loaded reranker model %s", MODEL_NAME)
            return self._model

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        if not documents:
            return []
        model = self._load()
        try:
            scores = [
                float(s)
                for s in model.rerank(query, list(documents), batch_size=BATCH_SIZE)
            ]
        except Exception as exc:
            logger.warning("Reranking failed: %s", type(exc).__name__)
            raise RerankerUnavailableError(
                "The results could not be reranked"
            ) from None
        return validate_scores(scores, len(documents))


def validate_scores(scores: list[float], expected: int) -> list[float]:
    """One finite score per document, or the ranking can't be trusted."""
    if len(scores) != expected or not all(math.isfinite(s) for s in scores):
        raise RerankerUnavailableError("The reranking model returned invalid scores")
    return scores
