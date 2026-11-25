"""The golden set's expectations against the loaded data (F6.1).

Opt-in and read-only, like the other corpus tests:

    CORPUS_DATABASE_URL=postgresql://…/apexgpt uv run pytest -m corpus

- every reference ``sql`` runs, and its rows contain every expected ``answer``
  value, so the expected stats come from the data;
- every expected source is an article in the chunks table.

Re-run it after a data reload: a failure means the golden set needs updating.
"""

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, create_engine, text

from app.core.config import normalise_database_url
from evals.golden import GoldenQuestion, load_golden_set, missing_values

pytestmark = pytest.mark.corpus

_URL = os.environ.get("CORPUS_DATABASE_URL")
if not _URL:
    pytest.skip("CORPUS_DATABASE_URL not set", allow_module_level=True)

GOLDEN = load_golden_set()
WITH_SQL = [q for q in GOLDEN.questions if q.sql]
WITH_SOURCES = [q for q in GOLDEN.questions if q.expect.sources]


@pytest.fixture(scope="module")
def conn() -> Iterator[Connection]:
    engine = create_engine(
        normalise_database_url(_URL), connect_args={"prepare_threshold": None}
    )
    with engine.connect() as connection:
        connection.execute(text("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY"))
        connection.execute(text("SET statement_timeout = '5s'"))
        yield connection
    engine.dispose()


@pytest.mark.parametrize("question", WITH_SQL, ids=lambda q: q.id)
def test_reference_sql_proves_the_expected_answer(
    conn: Connection, question: GoldenQuestion
) -> None:
    rows = conn.exec_driver_sql(question.sql).fetchall()
    conn.rollback()

    assert rows, f"{question.id}: the reference query returned no rows"
    missing = missing_values(rows, question.expect.answer)
    assert not missing, f"{question.id}: {missing} not in {rows}"


@pytest.mark.parametrize("question", WITH_SOURCES, ids=lambda q: q.id)
def test_expected_sources_are_in_the_corpus(
    conn: Connection, question: GoldenQuestion
) -> None:
    found = set(
        conn.execute(
            text("SELECT DISTINCT title FROM chunks WHERE title = ANY(:titles)"),
            {"titles": list(question.expect.sources)},
        ).scalars()
    )
    conn.rollback()

    assert found == set(
        question.expect.sources
    ), f"{question.id}: not in the corpus: {set(question.expect.sources) - found}"
