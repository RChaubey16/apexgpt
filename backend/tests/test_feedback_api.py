"""POST /api/feedback and the feedback store with a fake session (F4.3)."""

import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, OperationalError

from app.api.routes.feedback import UNAVAILABLE
from app.db.models.feedback import Feedback
from app.db.session import get_session
from app.feedback import RETENTION_DAYS, NewFeedback, excerpt, save_feedback
from app.feedback import __main__ as cli
from app.main import create_app

BODY = {
    "rating": "up",
    "question": "Who won the 1976 title?",
    "answer": "James Hunt won the 1976 title by one point [S1].",
    "provider": "groq",
    "model": "openai/gpt-oss-120b",
}


class FakeResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class FakeSession:
    def __init__(self, error: Exception | None = None, purged: int = 0) -> None:
        self.error, self.purged = error, purged
        self.added: list[Feedback] = []
        self.statements: list = []
        self.commits = 0

    def add(self, row: Feedback) -> None:
        self.added.append(row)

    def execute(self, statement):
        self.statements.append(statement)
        return FakeResult(self.purged)

    def commit(self) -> None:
        if self.error:
            raise self.error
        self.commits += 1
        for i, row in enumerate(self.added, start=1):
            row.id = i


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.conftest import make_settings

    monkeypatch.setattr(
        "app.main.get_settings", lambda: make_settings(environment="test")
    )


def client_with(session: FakeSession) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app)


# --- the endpoint ---


def test_feedback_is_stored_and_its_id_returned() -> None:
    session = FakeSession()

    response = client_with(session).post("/api/feedback", json=BODY)

    assert response.status_code == 201
    assert response.json() == {"id": 1}
    (row,) = session.added
    assert (row.rating, row.question, row.answer_excerpt, row.provider, row.model) == (
        "up",
        "Who won the 1976 title?",
        "James Hunt won the 1976 title by one point [S1].",
        "groq",
        "openai/gpt-oss-120b",
    )
    assert session.commits == 1
    assert len(session.statements) == 1  # the retention purge, same transaction


def test_only_rating_question_and_answer_are_required() -> None:
    session = FakeSession()
    body = {"rating": "down", "question": "  q  ", "answer": "  a  "}

    assert client_with(session).post("/api/feedback", json=body).status_code == 201
    (row,) = session.added
    assert (row.question, row.answer_excerpt, row.provider, row.model) == (
        "q",
        "a",
        None,
        None,
    )


def test_a_long_answer_is_stored_as_an_excerpt() -> None:
    session = FakeSession()
    body = BODY | {"answer": "word " * 1600}  # 8,000 characters

    assert client_with(session).post("/api/feedback", json=body).status_code == 201
    stored = session.added[0].answer_excerpt
    assert len(stored) <= 500 and stored.endswith("word…")


@pytest.mark.parametrize(
    "change",
    [
        {"rating": "meh"},
        {"rating": None},
        {"rating": 1},
        {"question": ""},
        {"question": "   "},
        {"question": "x" * 501},
        {"answer": ""},
        {"answer": "x" * 8001},
        {"provider": ""},
        {"provider": "x" * 41},
        {"model": "x" * 201},
        {"ip": "1.2.3.4"},  # unknown fields are rejected
    ],
)
def test_bad_bodies_are_422_and_store_nothing(change) -> None:
    session = FakeSession()

    response = client_with(session).post("/api/feedback", json=BODY | change)

    assert response.status_code == 422
    assert session.added == []


@pytest.mark.parametrize("missing", ["rating", "question", "answer"])
def test_required_fields(missing) -> None:
    body = {k: v for k, v in BODY.items() if k != missing}

    assert (
        client_with(FakeSession()).post("/api/feedback", json=body).status_code == 422
    )


@pytest.mark.parametrize(
    "error",
    [
        OperationalError("INSERT", {}, Exception("db.internal:5432 password=x")),
        IntegrityError("INSERT", {}, Exception("check constraint")),
    ],
)
def test_a_database_failure_is_a_safe_503(error, caplog) -> None:
    client = client_with(FakeSession(error=error))
    # create_app's basicConfig(force=True) removes pytest's capture handler.
    logging.getLogger().addHandler(caplog.handler)

    response = client.post("/api/feedback", json=BODY)

    assert response.status_code == 503
    assert response.json() == {"detail": UNAVAILABLE}
    assert "password" not in response.text and "db.internal" not in caplog.text
    assert f"Feedback not saved: {type(error).__name__}" in caplog.text


def test_get_is_not_allowed() -> None:
    assert client_with(FakeSession()).get("/api/feedback").status_code == 405


# --- the store ---


@pytest.mark.parametrize(
    ("answer", "stored"),
    [
        ("Short answer.", "Short answer."),
        ("  padded  ", "padded"),
        ("x" * 500, "x" * 500),
        ("x" * 501, "x" * 499 + "…"),  # no space to cut at
        ("ab " * 200, ("ab " * 166).rstrip() + "…"),
    ],
)
def test_excerpt(answer: str, stored: str) -> None:
    assert excerpt(answer) == stored
    assert len(excerpt(answer)) <= 500


def test_save_logs_how_many_rows_were_purged(caplog) -> None:
    caplog.set_level(logging.INFO)
    session = FakeSession(purged=3)

    assert save_feedback(session, NewFeedback("up", "q", "a")) == 1  # type: ignore[arg-type]
    assert f"Feedback purged: 3 rows older than {RETENTION_DAYS} days" in caplog.text


def test_the_purge_deletes_by_age() -> None:
    session = FakeSession()

    save_feedback(session, NewFeedback("down", "q", "a"))  # type: ignore[arg-type]

    (statement,) = session.statements
    sql = str(statement.compile())
    assert sql.startswith("DELETE FROM feedback WHERE feedback.created_at <")
    assert "now()" in sql


# --- the CLI ---


def test_cli_purge(monkeypatch, capsys) -> None:
    calls = []

    class FakeEngine:
        def dispose(self) -> None:
            calls.append("dispose")

    class CliSession(FakeSession):
        def __init__(self, engine) -> None:
            super().__init__(purged=2)

        def __enter__(self):
            return self

        def __exit__(self, *exc) -> None:
            calls.append("closed")

        def commit(self) -> None:
            calls.append("commit")

    monkeypatch.setattr(cli, "get_settings", lambda: None)
    monkeypatch.setattr(cli, "create_db_engine", lambda settings: FakeEngine())
    monkeypatch.setattr(cli, "Session", CliSession)

    assert cli.run(["purge"]) == 0
    assert capsys.readouterr().out == "purged 2 feedback rows older than 90 days\n"
    assert calls == ["commit", "closed", "dispose"]


def test_cli_database_error(monkeypatch, capsys) -> None:
    class Broken(FakeSession):
        def __init__(self, engine) -> None:
            super().__init__()

        def __enter__(self):
            raise OperationalError("SELECT", {}, Exception("host=db.internal"))

        def __exit__(self, *exc) -> None:
            pass

    monkeypatch.setattr(cli, "get_settings", lambda: None)
    monkeypatch.setattr(
        cli,
        "create_db_engine",
        lambda settings: type("E", (), {"dispose": lambda self: None})(),
    )
    monkeypatch.setattr(cli, "Session", Broken)

    assert cli.run(["purge"]) == 1
    err = capsys.readouterr().err
    assert err == "error: database unavailable (OperationalError)\n"


def test_cli_needs_a_command(capsys) -> None:
    with pytest.raises(SystemExit) as exit_:
        cli.run([])
    assert exit_.value.code == 2
