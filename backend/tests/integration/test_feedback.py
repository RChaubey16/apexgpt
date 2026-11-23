"""Feedback on real Postgres (F4.3): migration 0008, POST /api/feedback, the
90-day retention and the constraints.

Skipped unless TEST_DATABASE_URL is set (see test_database.py for the warning).
"""

from collections.abc import Iterator

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Feedback
from app.feedback import NewFeedback, purge_expired, save_feedback
from app.main import create_app
from tests.conftest import make_settings
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
def db(engine: Engine) -> Iterator[Engine]:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM feedback"))
    yield engine


def _insert(engine: Engine, age_days: float, question: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO feedback (created_at, rating, question, answer_excerpt) "
                "VALUES (now() - make_interval(secs => :secs), 'up', :q, 'a')"
            ),
            {"secs": age_days * 86400, "q": question},
        )


def _questions(engine: Engine) -> list[str]:
    with engine.connect() as conn:
        return list(
            conn.execute(text("SELECT question FROM feedback ORDER BY id")).scalars()
        )


def test_the_endpoint_stores_feedback(db: Engine) -> None:
    client = TestClient(create_app(make_settings(database_url=f1.DATABASE_URL)))
    body = {
        "rating": "down",
        "question": "How many poles did Senna get in 1988?",
        "answer": "Senna took 7 poles. " * 100,
        "provider": "groq",
        "model": "openai/gpt-oss-120b",
    }

    response = client.post("/api/feedback", json=body)

    assert response.status_code == 201
    with db.connect() as conn:
        row = conn.execute(
            text(
                "SELECT id, rating, question, answer_excerpt, provider, model, "
                "now() - created_at < interval '1 minute' AS recent FROM feedback"
            )
        ).one()
    assert row.id == response.json()["id"]
    assert (row.rating, row.question, row.provider, row.model, row.recent) == (
        "down",
        "How many poles did Senna get in 1988?",
        "groq",
        "openai/gpt-oss-120b",
        True,
    )
    assert len(row.answer_excerpt) <= 500 and row.answer_excerpt.endswith("…")


def test_the_purge_deletes_only_rows_older_than_90_days(db: Engine) -> None:
    _insert(db, 120, "old")
    _insert(db, 90.01, "just expired")
    _insert(db, 89.99, "just kept")
    _insert(db, 0, "new")

    with Session(db) as session:
        assert purge_expired(session) == 2
        session.commit()

    assert _questions(db) == ["just kept", "new"]


def test_saving_purges_expired_rows_in_the_same_transaction(db: Engine) -> None:
    _insert(db, 100, "old")

    with Session(db) as session:
        new_id = save_feedback(session, NewFeedback("up", "fresh", "an answer"))

    assert isinstance(new_id, int)
    assert _questions(db) == ["fresh"]


def test_a_failed_save_keeps_the_expired_rows_too(db: Engine) -> None:
    """One transaction: if the insert fails, the purge is rolled back with it."""
    _insert(db, 100, "old")

    with Session(db) as session, pytest.raises(IntegrityError):
        save_feedback(session, NewFeedback("meh", "q", "a"))  # type: ignore[arg-type]

    assert _questions(db) == ["old"]


@pytest.mark.parametrize(
    "values",
    [
        {"rating": "meh"},
        {"question": ""},
        {"question": "x" * 501},
        {"answer_excerpt": ""},
        {"answer_excerpt": "x" * 501},
        {"provider": "x" * 41},
        {"model": "x" * 201},
    ],
)
def test_constraints(db: Engine, values: dict) -> None:
    row = {"rating": "up", "question": "q", "answer_excerpt": "a"} | values

    with Session(db) as session, pytest.raises(IntegrityError):
        session.add(Feedback(**row))
        session.commit()


def test_the_llm_role_cannot_read_feedback(db: Engine) -> None:
    with db.connect() as conn:
        allowed = conn.execute(
            text(
                "SELECT has_table_privilege('apexgpt_llm_reader', 'feedback', 'SELECT')"
            )
        ).scalar_one()
    assert allowed is False


def test_downgrade_to_0007_drops_the_table(engine: Engine) -> None:
    command.downgrade(f1._alembic_config(), "0007")
    try:
        assert "feedback" not in inspect(engine).get_table_names()
    finally:
        command.upgrade(f1._alembic_config(), "head")
    assert "feedback" in inspect(engine).get_table_names()
