import pytest

from app.retrieval.fusion import RRF_K, Ranking, reciprocal_rank_fusion

A0, A1, A2 = (1, 0), (1, 1), (1, 2)
B0, C0, D0 = (2, 0), (3, 0), (4, 0)


def keys(fused: list) -> list[tuple[int, int]]:
    return [f.key for f in fused]


def test_scores_are_weighted_reciprocal_ranks() -> None:
    fused = reciprocal_rank_fusion(
        [Ranking("vector", [B0, C0]), Ranking("text", [C0], weight=0.5)], limit=10
    )

    scores = {f.key: f.score for f in fused}
    assert scores[B0] == pytest.approx(1 / (RRF_K + 1))
    assert scores[C0] == pytest.approx(1 / (RRF_K + 2) + 0.5 / (RRF_K + 1))
    assert keys(fused) == [C0, B0]  # found by both lists beats one first place


def test_signals_name_every_list_that_found_the_chunk() -> None:
    fused = reciprocal_rank_fusion(
        [Ranking("vector", [B0, C0]), Ranking("text", [C0]), Ranking("article", [D0])],
        limit=10,
    )

    signals = {f.key: f.signals for f in fused}
    assert signals == {B0: ("vector",), C0: ("vector", "text"), D0: ("article",)}


def test_at_most_two_chunks_per_article_by_default() -> None:
    fused = reciprocal_rank_fusion([Ranking("vector", [A0, A1, A2, B0])], limit=10)

    assert keys(fused) == [A0, A1, B0]


def test_per_article_cap_can_be_changed_or_disabled() -> None:
    ranking = [Ranking("vector", [A0, A1, A2, B0])]

    assert keys(reciprocal_rank_fusion(ranking, limit=10, per_article=1)) == [A0, B0]
    assert keys(reciprocal_rank_fusion(ranking, limit=10, per_article=None)) == [
        A0,
        A1,
        A2,
        B0,
    ]


def test_limit_applies_after_the_cap() -> None:
    fused = reciprocal_rank_fusion(
        [Ranking("vector", [A0, A1, A2, B0, C0])], limit=3, per_article=2
    )

    assert keys(fused) == [A0, A1, B0]


def test_ties_are_broken_deterministically() -> None:
    # B0 and C0 both score 1/(k+1) with best rank 1.
    fused = reciprocal_rank_fusion(
        [Ranking("vector", [C0]), Ranking("text", [B0])], limit=10
    )

    assert keys(fused) == [B0, C0]  # equal score and rank: lower key first


def test_a_chunk_listed_twice_counts_once() -> None:
    fused = reciprocal_rank_fusion([Ranking("vector", [B0, B0, C0])], limit=10)

    assert fused[0].score == pytest.approx(1 / (RRF_K + 1))
    assert fused[1].score == pytest.approx(1 / (RRF_K + 3))


def test_empty_rankings_give_no_results() -> None:
    assert reciprocal_rank_fusion([Ranking("vector", [])], limit=5) == []
    assert reciprocal_rank_fusion([], limit=5) == []


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"limit": 0}, "limit"),
        ({"limit": 5, "k": 0}, "k must"),
        ({"limit": 5, "per_article": 0}, "per_article"),
    ],
)
def test_invalid_arguments_are_rejected(kwargs: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        reciprocal_rank_fusion([Ranking("vector", [B0])], **kwargs)


@pytest.mark.parametrize("weight", [0.0, -1.0])
def test_weights_must_be_positive(weight: float) -> None:
    with pytest.raises(ValueError, match="positive weight"):
        reciprocal_rank_fusion([Ranking("text", [B0], weight=weight)], limit=5)
