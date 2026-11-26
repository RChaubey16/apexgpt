"""Model prefetch for the production image (F7.1). Fake models, no downloads;
CI also runs the real one in the built image with no network."""

from pathlib import Path

import pytest

from app.retrieval import prefetch as module
from app.retrieval.embedder import DIMENSIONS
from app.retrieval.errors import EmbeddingUnavailableError, SearchError


class Embedder:
    calls: list[Path] = []
    vector = [0.0] * DIMENSIONS

    def __init__(self, cache_dir: Path) -> None:
        Embedder.calls.append(cache_dir)

    def embed_query(self, query: str) -> list[float]:
        return Embedder.vector


class Reranker:
    calls: list[Path] = []
    scores = [0.5]

    def __init__(self, cache_dir: Path) -> None:
        Reranker.calls.append(cache_dir)

    def score(self, query: str, documents: list[str]) -> list[float]:
        return Reranker.scores


@pytest.fixture(autouse=True)
def fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    Embedder.calls, Reranker.calls = [], []
    Embedder.vector, Reranker.scores = [0.0] * DIMENSIONS, [0.5]
    monkeypatch.setattr(module, "FastEmbedQueryEmbedder", Embedder)
    monkeypatch.setattr(module, "FastEmbedReranker", Reranker)


def test_both_models_are_loaded_into_the_directory(tmp_path: Path) -> None:
    target = tmp_path / "models" / "nested"
    assert module.main([str(target)]) == 0
    assert target.is_dir()
    assert Embedder.calls == Reranker.calls == [target]


@pytest.mark.parametrize(
    ("setup", "message"),
    [
        (lambda: setattr(Embedder, "vector", [0.0] * 3), "3 dimensions"),
        (lambda: setattr(Reranker, "scores", []), "no score"),
    ],
)
def test_a_wrong_model_fails(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    setup,
    message: str,  # noqa: ANN001
) -> None:
    setup()
    assert module.main([str(tmp_path)]) == 1
    assert message in capsys.readouterr().err


def test_a_model_that_cannot_load_fails_the_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken(self, query: str) -> list[float]:  # noqa: ANN001
        raise EmbeddingUnavailableError("The search model could not be loaded")

    monkeypatch.setattr(Embedder, "embed_query", broken)
    assert module.main([str(tmp_path)]) == 1
    assert "could not be loaded" in capsys.readouterr().err
    with pytest.raises(SearchError):
        module.prefetch(tmp_path)
