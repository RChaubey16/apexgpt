import sys
import threading
import types

import pytest

from app.retrieval.errors import RerankerUnavailableError, SearchError
from app.retrieval.reranker import (
    BATCH_SIZE,
    MODEL_NAME,
    FastEmbedReranker,
    validate_scores,
)


class FakeCrossEncoder:
    instances: list["FakeCrossEncoder"] = []

    def __init__(
        self, name: str, cache_dir: str | None = None, threads: int | None = None
    ) -> None:
        self.name, self.cache_dir, self.threads = name, cache_dir, threads
        self.calls: list[tuple[str, list[str], int]] = []
        FakeCrossEncoder.instances.append(self)

    def rerank(self, query: str, documents: list[str], batch_size: int):
        self.calls.append((query, documents, batch_size))
        return iter(float(len(d)) for d in documents)  # longer = "more relevant"


def install(monkeypatch: pytest.MonkeyPatch, cls: object) -> None:
    module = types.ModuleType("fastembed.rerank.cross_encoder")
    module.TextCrossEncoder = cls  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fastembed.rerank.cross_encoder", module)


@pytest.fixture
def fake_model(monkeypatch: pytest.MonkeyPatch) -> type[FakeCrossEncoder]:
    FakeCrossEncoder.instances = []
    install(monkeypatch, FakeCrossEncoder)
    return FakeCrossEncoder


def test_scores_each_document_one_at_a_time(fake_model: type[FakeCrossEncoder]) -> None:
    scores = FastEmbedReranker().score("Senna Suzuka", ["ab", "abcd"])

    (model,) = fake_model.instances
    assert model.name == MODEL_NAME and model.cache_dir is None
    assert model.threads == 1  # default: one ONNX thread (Settings.onnx_threads)
    assert model.calls == [("Senna Suzuka", ["ab", "abcd"], BATCH_SIZE)]
    assert BATCH_SIZE == 1  # batches raised peak memory by ~240 MB
    assert scores == [2.0, 4.0]


def test_cache_dir_and_threads_are_passed_on(
    fake_model: type[FakeCrossEncoder], tmp_path
) -> None:
    FastEmbedReranker(tmp_path, threads=3).score("q", ["d"])

    assert fake_model.instances[0].cache_dir == str(tmp_path)
    assert fake_model.instances[0].threads == 3


def test_nothing_to_score_does_not_load_the_model(
    fake_model: type[FakeCrossEncoder],
) -> None:
    assert FastEmbedReranker().score("q", []) == []
    assert fake_model.instances == []


def test_model_is_loaded_once_and_lazily(fake_model: type[FakeCrossEncoder]) -> None:
    reranker = FastEmbedReranker()
    assert fake_model.instances == []

    threads = [
        threading.Thread(target=reranker.score, args=("q", ["d"])) for _ in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(fake_model.instances) == 1
    assert len(fake_model.instances[0].calls) == 8


def test_load_failure_is_a_safe_search_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise OSError("download failed: https://secret-host/model?token=abc")

    install(monkeypatch, broken)

    with pytest.raises(RerankerUnavailableError, match="could not be loaded") as info:
        FastEmbedReranker().score("q", ["d"])

    assert isinstance(info.value, SearchError)
    assert info.value.__cause__ is None
    assert "secret-host" not in caplog.text and "OSError" in caplog.text


def test_scoring_failure_is_a_safe_search_error(
    fake_model: type[FakeCrossEncoder], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(self, query, documents, batch_size):
        raise RuntimeError("onnx exploded")

    monkeypatch.setattr(FakeCrossEncoder, "rerank", fail)

    with pytest.raises(RerankerUnavailableError, match="could not be reranked"):
        FastEmbedReranker().score("q", ["d"])


def test_too_few_scores_from_the_model_are_rejected(
    fake_model: type[FakeCrossEncoder], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        FakeCrossEncoder, "rerank", lambda self, q, docs, batch_size: iter([1.0])
    )

    with pytest.raises(RerankerUnavailableError, match="invalid scores"):
        FastEmbedReranker().score("q", ["a", "b"])


@pytest.mark.parametrize(
    ("scores", "expected"),
    [([1.0], 2), ([1.0, 2.0, 3.0], 2), ([float("nan"), 1.0], 2), ([float("inf")], 1)],
    ids=["too few", "too many", "nan", "inf"],
)
def test_invalid_scores_are_rejected(scores: list[float], expected: int) -> None:
    with pytest.raises(RerankerUnavailableError, match="invalid scores"):
        validate_scores(scores, expected)


def test_negative_scores_are_valid() -> None:
    assert validate_scores([-3.5, 0.0, 7.1], 3) == [-3.5, 0.0, 7.1]
