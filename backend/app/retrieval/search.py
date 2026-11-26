"""Hybrid knowledge search over the Wikipedia chunks (F3.1).

Three ranked candidate lists are fused with Reciprocal Rank Fusion:

1. vector: nearest chunks to the question's embedding (HNSW, cosine).
2. text: chunks containing every word of the question (full-text, GIN),
   ranked by ts_rank_cd.
3. article: articles containing every word somewhere, even if no single chunk
   does, each represented by its chunk nearest to the question. Race articles
   rarely name the circuit or the drivers in every section: "1989 Japanese
   Grand Prix" says "Suzuka" in the lead and describes the collision later.

Weights (vector 1.0, text 0.5, article 0.5), the 50 candidates per list and the
cap of 2 chunks per article were chosen on a labelled set of 15 questions; see
the F3.1 entry in docs/archive/v1.0.0-mvp/PROGRESS.md. Every list uses an index (~10 ms of SQL in
total on the full corpus), so no extra metadata indexes are needed.
"""

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models.narrative import CHUNK_TSVECTOR, TS_CONFIG
from app.retrieval.embedder import QueryEmbedder, validate_vector
from app.retrieval.errors import SearchError
from app.retrieval.filters import SearchFilters, filters_from_query
from app.retrieval.fusion import Ranking, reciprocal_rank_fusion

logger = logging.getLogger(__name__)

MAX_QUERY_CHARS = 500
MAX_LIMIT = 50
CANDIDATES = 50
WEIGHTS = {"vector": 1.0, "text": 0.5, "article": 0.5}
PER_ARTICLE = 2
# The article list needs every word: past this many, almost nothing matches and
# each word costs one index lookup, so the list is skipped.
MAX_ARTICLE_TERMS = 8
# HNSW candidates examined per search; must be at least CANDIDATES.
EF_SEARCH = 100

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SPACES = re.compile(r"\s+")

# Chunks of the filtered seasons and chunks with no season (filters.py).
_SEASON = (
    "(CAST(:seasons AS int[]) IS NULL OR c.season = ANY(CAST(:seasons AS int[])) "
    "OR c.season IS NULL)"
)
_TSV = CHUNK_TSVECTOR.replace("(title", "(c.title").replace("|| text)", "|| c.text)")

# One round trip: (source, rank, pageid, chunk_index) for all three lists.
# relaxed_order iterative scans keep HNSW fast under the season filter but may
# return rows slightly out of order, hence the outer ORDER BY.
# Only module constants are interpolated; user input is always a bound parameter.
_CANDIDATES_SQL = text(f"""
WITH vec AS (
    SELECT pageid, chunk_index, row_number() OVER (ORDER BY d) AS rank
    FROM (
        SELECT c.pageid, c.chunk_index, c.embedding <=> CAST(:vector AS halfvec) AS d
        FROM chunks c
        WHERE {_SEASON}
        ORDER BY d
        LIMIT :n
    ) nearest
),
txt AS (
    SELECT c.pageid, c.chunk_index,
           row_number() OVER (
               ORDER BY ts_rank_cd({_TSV}, q.query) DESC, c.pageid, c.chunk_index
           ) AS rank
    FROM chunks c, plainto_tsquery('{TS_CONFIG}', :query) q(query)
    WHERE {_TSV} @@ q.query AND {_SEASON}
    ORDER BY rank
    LIMIT :n
),
lex AS (
    SELECT DISTINCT lexeme
    FROM unnest(tsvector_to_array(to_tsvector('{TS_CONFIG}', :query))) lexeme
),
hits AS (
    SELECT lex.lexeme, page.pageid
    FROM lex
    CROSS JOIN LATERAL (
        SELECT DISTINCT c.pageid FROM chunks c
        -- The lexeme is already stemmed and folded; 'simple' keeps it as is
        -- and, unlike a ::tsquery cast, can't fail on odd characters.
        WHERE {_TSV} @@ plainto_tsquery('simple', lex.lexeme)
    ) page
    WHERE (SELECT count(*) FROM lex) <= :max_terms
),
articles AS (
    SELECT pageid FROM hits
    GROUP BY pageid
    HAVING count(*) = (SELECT count(*) FROM lex)
),
best AS (
    SELECT DISTINCT ON (c.pageid)
           c.pageid, c.chunk_index, c.embedding <=> CAST(:vector AS halfvec) AS d
    FROM chunks c JOIN articles USING (pageid)
    WHERE {_SEASON}
    ORDER BY c.pageid, d, c.chunk_index
),
art AS (
    SELECT pageid, chunk_index, row_number() OVER (ORDER BY d, pageid) AS rank
    FROM best
    ORDER BY rank
    LIMIT :n
)
SELECT 'vector' AS source, rank, pageid, chunk_index FROM vec
UNION ALL SELECT 'text', rank, pageid, chunk_index FROM txt
UNION ALL SELECT 'article', rank, pageid, chunk_index FROM art
""")  # noqa: S608

_ROWS_SQL = text("""
SELECT c.pageid, c.chunk_index, c.title, c.section, c.text, c.source_url,
       c.season, c.race_id
FROM chunks c
JOIN unnest(CAST(:pageids AS int[]), CAST(:indexes AS int[])) AS k(pageid, chunk_index)
  ON c.pageid = k.pageid AND c.chunk_index = k.chunk_index
""")


@dataclass(frozen=True)
class SearchResult:
    pageid: int
    chunk_index: int
    title: str
    # Heading path ("Race > Race report"); None for an article's lead.
    section: str | None
    text: str
    source_url: str
    season: int | None
    race_id: int | None
    # RRF score: only meaningful for ordering results of the same search.
    # After reranking it is the blended score (retriever.py).
    score: float
    # Which lists found it: "vector", "text", "article".
    signals: tuple[str, ...]
    # The cross-encoder's relevance score; None when the result wasn't reranked.
    rerank_score: float | None = None

    @property
    def heading(self) -> str:
        """'Title > Section', or the title for an article's lead."""
        return f"{self.title} > {self.section}" if self.section else self.title


def normalise_query(query: str) -> str:
    """Collapse whitespace and drop control characters; reject empty or huge input."""
    if not isinstance(query, str):
        raise ValueError("query must be a string")
    cleaned = _SPACES.sub(" ", _CONTROL.sub(" ", query)).strip()
    if not cleaned:
        raise ValueError("query must not be empty")
    if len(cleaned) > MAX_QUERY_CHARS:
        raise ValueError(f"query must be at most {MAX_QUERY_CHARS} characters")
    return cleaned


def _vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


class HybridSearcher:
    def __init__(self, embedder: QueryEmbedder) -> None:
        self._embedder = embedder

    def search(
        self,
        session: Session,
        query: str,
        *,
        filters: SearchFilters | None = None,
        limit: int = 10,
    ) -> list[SearchResult]:
        """The `limit` best chunks for `query`, best first.

        filters=None extracts them from the question (years → seasons); pass
        SearchFilters() to search without any. Raises ValueError for bad input
        and SearchError when the database or the model fails.
        """
        query = normalise_query(query)
        if not 1 <= limit <= MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
        if filters is None:
            filters = filters_from_query(query)
        vector = validate_vector(self._embedder.embed_query(query))

        params = {
            "query": query,
            "vector": _vector_literal(vector),
            "seasons": list(filters.seasons) or None,
            "n": CANDIDATES,
            "max_terms": MAX_ARTICLE_TERMS,
        }
        try:
            # Transaction-local, so safe behind Neon's pooler (transaction mode).
            session.execute(
                text(
                    "SELECT set_config('hnsw.ef_search', :ef, true), "
                    "set_config('hnsw.iterative_scan', 'relaxed_order', true)"
                ),
                {"ef": str(EF_SEARCH)},
            )
            candidates = session.execute(_CANDIDATES_SQL, params).all()
            lists: dict[str, list[tuple[int, int]]] = {name: [] for name in WEIGHTS}
            for row in sorted(candidates, key=lambda row: (row.source, row.rank)):
                lists[row.source].append((row.pageid, row.chunk_index))
            fused = reciprocal_rank_fusion(
                [Ranking(name, keys, WEIGHTS[name]) for name, keys in lists.items()],
                limit=limit,
                per_article=PER_ARTICLE,
            )
            if not fused:
                return []
            rows = session.execute(
                _ROWS_SQL,
                {
                    "pageids": [f.key[0] for f in fused],
                    "indexes": [f.key[1] for f in fused],
                },
            ).all()
        except SQLAlchemyError as exc:
            # The class only: driver messages can include host details.
            logger.warning("Knowledge search failed: %s", type(exc).__name__)
            raise SearchError("Knowledge search is unavailable right now") from None

        by_key = {(row.pageid, row.chunk_index): row for row in rows}
        results = []
        for item in fused:
            row = by_key.get(item.key)
            if row is None:  # deleted by a concurrent ingestion sync
                continue
            results.append(
                SearchResult(
                    pageid=row.pageid,
                    chunk_index=row.chunk_index,
                    title=row.title,
                    section=row.section,
                    text=row.text,
                    source_url=row.source_url,
                    season=row.season,
                    race_id=row.race_id,
                    score=item.score,
                    signals=item.signals,
                )
            )
        return results
