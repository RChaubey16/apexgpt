import re
import sys
import threading
import types
from pathlib import Path

import numpy as np
import pytest

from app.retrieval.embedder import (
    DIMENSIONS,
    MODEL_NAME,
    QUERY_INSTRUCTION,
    FastEmbedQueryEmbedder,
    validate_vector,
)
from app.retrieval.errors import EmbeddingUnavailableError, SearchError

INGESTION_EMBEDDER = (
    Path(__file__).resolve().parents[3] / "ingestion" / "narrative" / "embedder.py"
)


class FakeModel:
    instances: list["FakeModel"] = []

    def __init__(self, name: str, cache_dir: str | None = None) -> None:
        self.name, self.cache_dir = name, cache_dir
        self.queries: list[str] = []
        FakeModel.instances.append(self)

    def query_embed(self, texts: list[str]):
        self.queries.extend(texts)
        return iter([np.full(DIMENSIONS, 0.05, dtype=np.float32) for _ in texts])


@pytest.fixture
def fake_fastembed(monkeypatch: pytest.MonkeyPatch) -> type[FakeModel]:
    FakeModel.instances = []
    module = types.ModuleType("fastembed")
    module.TextEmbedding = FakeModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fastembed", module)
    return FakeModel


def test_model_matches_the_ingestion_pipeline() -> None:
    if not INGESTION_EMBEDDER.exists():  # e.g. inside the backend Docker image
        pytest.skip("ingestion/ is not available")
    match = re.search(r'^MODEL_NAME = "([^"]+)"', INGESTION_EMBEDDER.read_text(), re.M)
    assert match is not None
    assert match.group(1) == MODEL_NAME


def test_queries_get_the_retrieval_instruction(fake_fastembed: type[FakeModel]) -> None:
    vector = FastEmbedQueryEmbedder(Path("/models")).embed_query("Lauda 1976")

    (model,) = fake_fastembed.instances
    assert (model.name, model.cache_dir) == (MODEL_NAME, "/models")
    assert model.queries == [QUERY_INSTRUCTION + "Lauda 1976"]
    assert len(vector) == DIMENSIONS
    assert vector[0] == pytest.approx(0.05)


def test_no_cache_dir_uses_the_fastembed_default(
    fake_fastembed: type[FakeModel],
) -> None:
    FastEmbedQueryEmbedder().embed_query("x")

    assert fake_fastembed.instances[0].cache_dir is None


def test_model_is_loaded_once_and_lazily(fake_fastembed: type[FakeModel]) -> None:
    embedder = FastEmbedQueryEmbedder()
    assert fake_fastembed.instances == []  # nothing loaded at construction

    threads = [
        threading.Thread(target=embedder.embed_query, args=("q",)) for _ in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(fake_fastembed.instances) == 1
    assert len(fake_fastembed.instances[0].queries) == 8


def test_load_failure_is_a_clear_search_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise OSError("download failed: https://secret-host/path?token=abc")

    module = types.ModuleType("fastembed")
    module.TextEmbedding = broken  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fastembed", module)

    with pytest.raises(EmbeddingUnavailableError, match="could not be loaded") as info:
        FastEmbedQueryEmbedder().embed_query("q")

    assert isinstance(info.value, SearchError)
    assert info.value.__cause__ is None
    assert "token" not in caplog.text and "secret-host" not in caplog.text
    assert "OSError" in caplog.text


def test_embedding_failure_is_a_clear_search_error(
    fake_fastembed: type[FakeModel], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(self: FakeModel, texts: list[str]):
        raise RuntimeError("onnx exploded")

    monkeypatch.setattr(FakeModel, "query_embed", fail)

    with pytest.raises(EmbeddingUnavailableError, match="could not be embedded"):
        FastEmbedQueryEmbedder().embed_query("q")


@pytest.mark.parametrize(
    "vector",
    [
        [],
        [0.1] * (DIMENSIONS - 1),
        [float("nan")] * DIMENSIONS,
        [float("inf")] * DIMENSIONS,
    ],
    ids=["empty", "short", "nan", "inf"],
)
def test_invalid_vectors_are_rejected(vector: list[float]) -> None:
    with pytest.raises(EmbeddingUnavailableError, match="invalid vector"):
        validate_vector(vector)


def test_model_returning_nothing_is_rejected(
    fake_fastembed: type[FakeModel], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(FakeModel, "query_embed", lambda self, texts: iter([]))

    with pytest.raises(EmbeddingUnavailableError):
        FastEmbedQueryEmbedder().embed_query("q")
