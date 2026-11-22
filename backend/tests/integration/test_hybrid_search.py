"""Hybrid search (F3.1) and migration 0007 against real Postgres + pgvector.

Skipped unless TEST_DATABASE_URL is set (see test_database.py for the warning).
Chunks are hand-made; a fake embedder gives each query a fixed vector, so the
vector list's order is known and the text/article lists can be checked alone.
"""

from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from app.db.models import Chunk, Season
from app.db.models.narrative import TS_CONFIG
from app.retrieval.embedder import DIMENSIONS
from app.retrieval.filters import NO_FILTERS, SearchFilters
from app.retrieval.retriever import KnowledgeRetriever
from app.retrieval.search import _CANDIDATES_SQL, HybridSearcher
from tests.integration import test_f1_schema as f1

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    """A freshly migrated, empty schema (whatever ran before), reset afterwards."""
    command.downgrade(f1._alembic_config(), "base")
    command.upgrade(f1._alembic_config(), "head")
    eng = create_engine(f1.DATABASE_URL, connect_args={"prepare_threshold": None})
    yield eng
    eng.dispose()
    command.downgrade(f1._alembic_config(), "base")


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """Rolled back after each test, so tests don't share rows."""
    with engine.connect() as conn:
        trans = conn.begin()
        with Session(bind=conn, join_transaction_mode="create_savepoint") as s:
            yield s
        trans.rollback()


def one_hot(dimension: int) -> list[float]:
    return [1.0 if i == dimension else 0.0 for i in range(DIMENSIONS)]


class FixedEmbedder:
    """Every query embeds to the same direction (default: dimension 0)."""

    def __init__(self, dimension: int = 0) -> None:
        self.vector = one_hot(dimension)

    def embed_query(self, query: str) -> list[float]:
        return self.vector


def make_chunk(
    pageid: int, index: int, title: str, body: str, **extra: object
) -> Chunk:
    values: dict[str, object] = {
        "pageid": pageid,
        "chunk_index": index,
        "title": title,
        "section": None if index == 0 else "Race",
        "text": body,
        "tokens": 50,
        "source_url": f"https://en.wikipedia.org/?curid={pageid}",
        "revid": 1,
        "depth": "race",
        "kinds": ["race"],
        "driver_ids": [],
        "constructor_ids": [],
        "content_hash": "0" * 32,
        # Far from the query by default; tests pull chunks closer explicitly.
        "embedding": one_hot(100 + pageid * 10 + index),
    }
    return Chunk(**(values | extra))


def search(session: Session, query: str, embedder=None, **kwargs) -> list:
    return HybridSearcher(embedder or FixedEmbedder()).search(session, query, **kwargs)


def found(results: list) -> list[tuple[int, int]]:
    return [(r.pageid, r.chunk_index) for r in results]


# --- migration 0007 ---


def test_tsvector_index_uses_the_accent_folding_config(engine: Engine) -> None:
    with engine.connect() as conn:
        indexdef = conn.execute(
            text(
                "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_chunks_tsvector'"
            )
        ).scalar_one()
        folded = conn.execute(
            text("SELECT to_tsvector(:cfg, 'Nürburgring Räikkönen Pérez')::text"),
            {"cfg": TS_CONFIG},
        ).scalar_one()
    assert "USING gin" in indexdef and f"'{TS_CONFIG}'::regconfig" in indexdef
    assert folded == "'nurburgr':1 'perez':3 'raikkonen':2"


def test_downgrade_to_0006_restores_the_english_index(engine: Engine) -> None:
    command.downgrade(f1._alembic_config(), "0006")
    try:
        with engine.connect() as conn:
            indexdef = conn.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE indexname = 'ix_chunks_tsvector'"
                )
            ).scalar_one()
            leftovers = conn.execute(
                text(
                    "SELECT (SELECT count(*) FROM pg_ts_config WHERE cfgname = :cfg)"
                    " + (SELECT count(*) FROM pg_extension WHERE extname = 'unaccent')"
                ),
                {"cfg": TS_CONFIG},
            ).scalar_one()
        assert "'english'::regconfig" in indexdef
        assert leftovers == 0
    finally:
        command.upgrade(f1._alembic_config(), "head")


# --- search ---


def test_vector_list_ranks_the_nearest_chunk_first(session: Session) -> None:
    session.add_all(
        [
            make_chunk(1, 0, "Monaco Grand Prix", "A street circuit."),
            make_chunk(2, 0, "Spa", "Eau Rouge.", embedding=one_hot(0)),
        ]
    )
    session.flush()

    results = search(session, "where is Eau Rouge")

    assert found(results)[0] == (2, 0)
    assert "vector" in results[0].signals


def test_text_list_needs_every_word_in_one_chunk(session: Session) -> None:
    session.add_all(
        [
            make_chunk(1, 0, "1990 Japanese Grand Prix", "Senna hit Prost at Suzuka."),
            make_chunk(2, 0, "Ayrton Senna", "Senna won in Monaco."),
        ]
    )
    session.flush()

    by_key = {found([r])[0]: r for r in search(session, "Senna Prost Suzuka")}

    assert "text" in by_key[(1, 0)].signals
    assert "text" not in by_key[(2, 0)].signals


def test_title_words_count_for_the_text_list(session: Session) -> None:
    session.add(
        make_chunk(1, 1, "1989 Japanese Grand Prix", "Senna and Prost collided.")
    )
    session.flush()

    (result,) = search(session, "Japanese Prost collided")

    assert "text" in result.signals


def test_accents_are_folded_both_ways(session: Session) -> None:
    session.add_all(
        [
            make_chunk(
                1, 0, "1976 German Grand Prix", "Lauda crashed at the Nürburgring."
            ),
            make_chunk(2, 0, "Kimi Raikkonen", "Raikkonen won the 2007 title."),
        ]
    )
    session.flush()

    plain = {found([r])[0]: r.signals for r in search(session, "Nurburgring crash")}
    accented = {found([r])[0]: r.signals for r in search(session, "Räikkönen title")}

    assert "text" in plain[(1, 0)]
    assert "text" in accented[(2, 0)]


def test_article_list_matches_words_spread_over_an_article(session: Session) -> None:
    session.add_all(
        [
            # No single chunk has all four words; the article does.
            make_chunk(1, 0, "1989 Japanese Grand Prix", "Held at Suzuka."),
            make_chunk(1, 1, "1989 Japanese Grand Prix", "Senna and Prost: collision."),
            # The nearer of the article's chunks represents it.
            make_chunk(
                1, 2, "1989 Japanese Grand Prix", "Podium.", embedding=one_hot(0)
            ),
            # Has three of the four words only.
            make_chunk(2, 0, "Prost–Senna rivalry", "Senna and Prost at Suzuka."),
        ]
    )
    session.flush()

    results = {
        found([r])[0]: r.signals
        for r in search(session, "Senna Prost Suzuka collision")
    }

    assert "article" in results[(1, 2)]
    assert "article" not in results.get((1, 0), ())
    assert "article" not in results.get((1, 1), ())
    assert "article" not in results[(2, 0)]


def test_season_filter_keeps_untagged_chunks(session: Session) -> None:
    session.add_all(
        [
            Season(year=y, wikipedia_url=f"https://en.wikipedia.org/wiki/{y}")
            for y in (1976, 1977)
        ]
    )
    session.flush()
    session.add_all(
        [
            make_chunk(
                1, 0, "1976 Japanese Grand Prix", "Hunt took the title.", season=1976
            ),
            make_chunk(
                2, 0, "1977 Japanese Grand Prix", "Hunt won the race.", season=1977
            ),
            make_chunk(3, 0, "James Hunt", "Hunt was champion in 1976.", depth="full"),
        ]
    )
    session.flush()

    extracted = found(search(session, "Hunt 1976"))
    unfiltered = found(search(session, "Hunt 1976", filters=NO_FILTERS))
    explicit = found(search(session, "Hunt", filters=SearchFilters(seasons=(1977,))))

    assert sorted(extracted) == [(1, 0), (3, 0)]
    assert sorted(unfiltered) == [(1, 0), (2, 0), (3, 0)]
    assert sorted(explicit) == [(2, 0), (3, 0)]


def test_at_most_two_chunks_per_article(session: Session) -> None:
    session.add_all(
        [
            make_chunk(1, i, "Prost–Senna rivalry", f"Senna Prost part {i}.")
            for i in range(4)
        ]
        + [make_chunk(2, 0, "Alain Prost", "Prost and Senna.")]
    )
    session.flush()

    results = found(search(session, "Senna Prost"))

    assert sum(1 for pageid, _ in results if pageid == 1) == 2
    assert (2, 0) in results


def test_results_carry_metadata_and_respect_the_limit(session: Session) -> None:
    session.add_all(
        [make_chunk(i, 0, f"Race {i}", f"Race {i} report.") for i in range(1, 8)]
    )
    session.flush()

    results = search(session, "race report", limit=3)

    assert len(results) == 3
    first = results[0]
    assert first.title.startswith("Race ") and first.text.endswith("report.")
    assert first.source_url.startswith("https://en.wikipedia.org/")
    assert first.section is None and first.season is None


@pytest.mark.parametrize(
    "query", ["the and of", "?!", 'Nürburgring\'s "quoted" (x) & | !']
)
def test_odd_queries_still_run(session: Session, query: str) -> None:
    session.add(make_chunk(1, 0, "Monaco", "A street circuit.", embedding=one_hot(0)))
    session.flush()

    assert found(search(session, query)) == [(1, 0)]  # vector list still answers


def test_too_many_words_skip_only_the_article_list(session: Session) -> None:
    words = "alpha beta gamma delta epsilon zeta eta theta iota"  # 9 > 8
    session.add(make_chunk(1, 0, "Greek", f"{words}."))
    session.flush()

    (result,) = search(session, words)

    assert result.signals == ("vector", "text")


def test_empty_corpus_returns_nothing(session: Session) -> None:
    assert search(session, "Senna Prost Suzuka collision") == []


def test_every_list_can_use_an_index(session: Session) -> None:
    session.add_all(
        [
            make_chunk(i, 0, f"Race {i}", "Senna and Prost at Suzuka.")
            for i in range(1, 30)
        ]
    )
    session.flush()
    session.execute(text("SET LOCAL enable_seqscan = off"))
    session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))

    plan = "\n".join(
        row[0]
        for row in session.execute(
            text("EXPLAIN " + _CANDIDATES_SQL.text),
            {
                "query": "Senna Suzuka",
                "vector": "[" + ",".join(map(str, one_hot(0))) + "]",
                "seasons": None,
                "n": 50,
                "max_terms": 8,
            },
        )
    )

    assert "ix_chunks_embedding_hnsw" in plan
    assert plan.count("ix_chunks_tsvector") >= 2  # text list + per-word article lookups


# --- F3.2: retrieval with reranking ---


class KeywordReranker:
    """Scores a document 1 if it mentions "Suzuka", else 0."""

    def score(self, query: str, documents: list[str]) -> list[float]:
        return [1.0 if "Suzuka" in d else 0.0 for d in documents]


def test_retriever_reranks_database_results(session: Session) -> None:
    session.add_all(
        [
            make_chunk(i, 0, f"Race {i}", "Senna and Prost.", embedding=one_hot(0))
            for i in range(1, 7)
        ]
        + [make_chunk(9, 0, "1989 Japanese Grand Prix", "Senna and Prost at Suzuka.")]
    )
    session.flush()
    retriever = KnowledgeRetriever(HybridSearcher(FixedEmbedder()), KeywordReranker())

    reranked = retriever.retrieve(session, "Senna Prost", top_k=3)
    hybrid = KnowledgeRetriever(HybridSearcher(FixedEmbedder()), None).retrieve(
        session, "Senna Prost", top_k=3
    )

    # Far in vector space (hybrid #7), lifted into the top 3 by the reranker.
    assert "1989 Japanese Grand Prix" not in [r.title for r in hybrid]
    assert "1989 Japanese Grand Prix" in [r.title for r in reranked]
    for r in reranked:  # each score belongs to its own row
        assert r.rerank_score == (1.0 if "Suzuka" in r.text else 0.0)


# --- F3.6: the search_f1_knowledge tool over the real query path ---


def test_knowledge_tool_returns_cited_chunks(session: Session) -> None:
    from contextlib import nullcontext

    from app.tools.knowledge import KnowledgeTool

    session.add_all(
        [
            make_chunk(1, 0, "1989 Japanese Grand Prix", "Senna and Prost collided at the chicane.",
                       embedding=one_hot(0)),
            make_chunk(2, 0, "Monaco Grand Prix", "A street circuit."),
        ]
    )  # fmt: skip
    session.flush()
    tool = KnowledgeTool(
        KnowledgeRetriever(HybridSearcher(FixedEmbedder()), None),
        lambda: nullcontext(session),  # keep the test's rolled-back session open
    )

    outcome = tool.call({"query": "Senna Prost chicane"}, first_source_number=7)

    assert outcome.ok
    first = outcome.payload["results"][0]
    assert (first["source"], first["title"]) == ("S7", "1989 Japanese Grand Prix")
    assert outcome.sources[0].url == "https://en.wikipedia.org/?curid=1"
    assert not tool.call({"query": "x", "seasons": [1800]}).ok
