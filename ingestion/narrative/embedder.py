"""Text embeddings for the narrative chunks: bge-small-en-v1.5 via fastembed (ONNX, CPU).

The backend must embed questions with the same model (MODEL_NAME), using the
query form (`query_embed`); chunks use the passage form.
"""

import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

MODEL_NAME = "BAAI/bge-small-en-v1.5"
DIMENSIONS = 384
# bge-small reads 512 tokens, [CLS] and [SEP] included; the rest is truncated.
MAX_MODEL_TOKENS = 512


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """One normalised vector per text, in order."""
        ...

    def truncated(self, texts: Sequence[str]) -> int:
        """How many of the texts are longer than the model reads."""
        ...


def content_hash(model_name: str, text: str) -> str:
    """Identifies an embedding: the same model and text give the same vector."""
    digest = hashlib.blake2b(digest_size=16)
    digest.update(model_name.encode())
    digest.update(b"\0")
    digest.update(text.encode())
    return digest.hexdigest()


class FastEmbedder:
    """fastembed's bge-small. The model (~65 MB) is downloaded once into `cache_dir`."""

    model_name = MODEL_NAME
    dimensions = DIMENSIONS

    def __init__(self, cache_dir: Path, batch_size: int = 16) -> None:
        from fastembed import TextEmbedding  # slow import; only when embedding

        self._model = TextEmbedding(MODEL_NAME, cache_dir=str(cache_dir))
        self._batch_size = batch_size

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [
            vector.tolist()
            for vector in self._model.passage_embed(
                list(texts), batch_size=self._batch_size
            )
        ]

    def truncated(self, texts: Sequence[str]) -> int:
        tokenizer = self._model.model.tokenizer
        return sum(bool(e.overflowing) for e in tokenizer.encode_batch(list(texts)))
