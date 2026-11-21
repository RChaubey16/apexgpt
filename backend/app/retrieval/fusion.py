"""Reciprocal Rank Fusion (RRF) of several ranked candidate lists.

score(chunk) = Σ weight_list / (k + rank_in_list), over the lists it appears in.
Ranks, not raw scores, are fused, so cosine distances and ts_rank values never
have to be put on one scale. k = 60 is the usual constant from the RRF paper.

`per_article` caps how many chunks of one article are kept, so one long article
(e.g. "Prost–Senna rivalry") can't fill every slot.
"""

from collections.abc import Sequence
from dataclasses import dataclass

# (pageid, chunk_index): the chunks table's primary key.
ChunkKey = tuple[int, int]

RRF_K = 60


@dataclass(frozen=True)
class Ranking:
    name: str
    keys: Sequence[ChunkKey]
    weight: float = 1.0


@dataclass(frozen=True)
class Fused:
    key: ChunkKey
    score: float
    # Names of the rankings that found this chunk, in the order they were given.
    signals: tuple[str, ...]


def reciprocal_rank_fusion(
    rankings: Sequence[Ranking],
    *,
    limit: int,
    k: int = RRF_K,
    per_article: int | None = 2,
) -> list[Fused]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if k < 1:
        raise ValueError("k must be at least 1")
    if per_article is not None and per_article < 1:
        raise ValueError("per_article must be at least 1 (or None for no cap)")

    scores: dict[ChunkKey, float] = {}
    best_rank: dict[ChunkKey, int] = {}
    signals: dict[ChunkKey, list[str]] = {}
    for ranking in rankings:
        if ranking.weight <= 0:
            raise ValueError(f"ranking {ranking.name!r} must have a positive weight")
        seen: set[ChunkKey] = set()
        for rank, key in enumerate(ranking.keys, start=1):
            if key in seen:  # a list counts each chunk once, at its best rank
                continue
            seen.add(key)
            scores[key] = scores.get(key, 0.0) + ranking.weight / (k + rank)
            best_rank[key] = min(best_rank.get(key, rank), rank)
            signals.setdefault(key, []).append(ranking.name)

    # Deterministic order: score, then best single rank, then key.
    ordered = sorted(scores, key=lambda key: (-scores[key], best_rank[key], key))
    fused: list[Fused] = []
    per_page: dict[int, int] = {}
    for key in ordered:
        pageid = key[0]
        if per_article is not None and per_page.get(pageid, 0) >= per_article:
            continue
        per_page[pageid] = per_page.get(pageid, 0) + 1
        fused.append(Fused(key, scores[key], tuple(signals[key])))
        if len(fused) == limit:
            break
    return fused
