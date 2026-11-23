"""Structured file logging (F4.5): the JSON format, handlers, rotation, and
the events the API writes."""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.answer.orchestrator import AnswerUnavailableError, QuestionEvent
from app.api.routes.chat import GENERIC_ERROR, event_frames, get_orchestrator
from app.core.logging import JsonFormatter, configure_logging
from app.db.session import get_session
from app.main import create_app
from tests.conftest import make_settings
from tests.test_chat_api import ANSWER, EVENTS, FakeOrchestrator
from tests.test_feedback_api import BODY, FakeSession


@pytest.fixture(autouse=True)
def restore_root_logger():
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    for handler in root.handlers:
        if handler not in handlers:
            handler.close()
    root.handlers[:] = handlers
    root.setLevel(level)


def lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def chat_events(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if getattr(r, "event", None) == "chat"]


# --- the format ---


def test_a_record_is_one_json_object_with_its_extra_fields() -> None:
    record = logging.makeLogRecord(
        {"name": "app.x", "levelname": "INFO", "levelno": 20, "msg": "Chat %s",
         "args": ("ok",), "created": 1795400000.123, "event": "chat",
         "tools": [{"name": "query_stats", "ok": True}], "question": "Räikkönen?"}
    )  # fmt: skip

    line = JsonFormatter().format(record)

    assert "\n" not in line
    assert json.loads(line) == {
        "ts": datetime.fromtimestamp(1795400000.123, UTC).isoformat(
            timespec="milliseconds"
        ),
        "level": "INFO",
        "logger": "app.x",
        "message": "Chat ok",
        "event": "chat",
        "tools": [{"name": "query_stats", "ok": True}],
        "question": "Räikkönen?",
    }
    assert "Räikkönen" in line  # not \\u-escaped


def test_exceptions_get_their_class_and_traceback() -> None:
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        import sys

        record = logging.makeLogRecord(
            {"msg": "failed", "levelname": "ERROR", "exc_info": sys.exc_info()}
        )

    entry = json.loads(JsonFormatter().format(record))

    assert entry["error"] == "RuntimeError"
    assert "RuntimeError: boom" in entry["traceback"]


def test_values_json_cannot_hold_are_written_as_repr() -> None:
    record = logging.makeLogRecord({"msg": "m", "path": Path("/x"), "ids": {1, 2}})

    entry = json.loads(JsonFormatter().format(record))

    assert entry["path"] == "PosixPath('/x')" and entry["ids"] == "{1, 2}"


# --- handlers ---


def test_the_file_gets_json_lines(tmp_path: Path) -> None:
    log_file = tmp_path / "logs" / "apexgpt.log"  # the directory is created
    configure_logging("INFO", log_file=log_file)

    logging.getLogger("app.test").info("hello", extra={"event": "chat", "n": 1})
    logging.getLogger("app.test").debug("hidden")

    (entry,) = lines(log_file)
    assert (entry["message"], entry["event"], entry["n"]) == ("hello", "chat", 1)


def test_reconfiguring_replaces_only_our_handlers(tmp_path: Path) -> None:
    foreign = logging.NullHandler()
    logging.getLogger().addHandler(foreign)

    configure_logging("INFO", log_file=tmp_path / "a.log")
    configure_logging("WARNING", log_file=tmp_path / "a.log")
    logging.getLogger("app.test").warning("once")

    root = logging.getLogger()
    assert foreign in root.handlers
    ours = [h for h in root.handlers if getattr(h, "_apexgpt_handler", False)]
    assert len(ours) == 2  # one console, one file
    assert root.level == logging.WARNING
    assert [e["message"] for e in lines(tmp_path / "a.log")] == ["once"]


def test_without_a_file_only_the_console_is_used() -> None:
    configure_logging("INFO")

    ours = [h for h in logging.getLogger().handlers
            if getattr(h, "_apexgpt_handler", False)]  # fmt: skip
    assert [type(h) for h in ours] == [logging.StreamHandler]


def test_the_file_rotates_by_size(tmp_path: Path) -> None:
    log_file = tmp_path / "apexgpt.log"
    configure_logging("INFO", log_file=log_file, max_bytes=2_000, backups=2)

    for i in range(100):
        logging.getLogger("app.test").info("line %d %s", i, "x" * 50)

    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == ["apexgpt.log", "apexgpt.log.1", "apexgpt.log.2"]
    assert all(p.stat().st_size <= 2_000 for p in tmp_path.iterdir())
    assert lines(log_file)[-1]["message"].startswith("line 99 ")


def test_an_unwritable_log_file_warns_and_keeps_running(tmp_path: Path, caplog) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")

    configure_logging("INFO", log_file=blocker / "apexgpt.log")

    assert "can't be opened" in caplog.text and "console only" in caplog.text
    ours = [h for h in logging.getLogger().handlers
            if getattr(h, "_apexgpt_handler", False)]  # fmt: skip
    assert [type(h) for h in ours] == [logging.StreamHandler]


# --- settings ---


def test_log_file_settings(tmp_path: Path) -> None:
    assert make_settings().log_file is None
    assert make_settings(log_file="  ").log_file is None
    assert (
        make_settings(log_file=str(tmp_path / "a.log")).log_file == tmp_path / "a.log"
    )
    settings = make_settings()
    assert (settings.log_file_max_mb, settings.log_file_backups) == (10, 5)


@pytest.mark.parametrize(
    "values",
    [{"log_file_max_mb": 0}, {"log_file_max_mb": 101},
     {"log_file_backups": 0}, {"log_file_backups": 21}],
)  # fmt: skip
def test_log_file_limits_are_bounded(values) -> None:
    with pytest.raises(ValidationError):
        make_settings(**values)


def test_a_directory_is_not_a_log_file(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="LOG_FILE"):
        make_settings(log_file=str(tmp_path))


# --- the chat event ---


def test_an_answer_logs_one_chat_event(caplog) -> None:
    caplog.set_level(logging.INFO)
    fake = FakeOrchestrator([QuestionEvent("Who won the 1976 title?"), *EVENTS])

    list(event_frames(fake, "And who won?", ["h1", "h2"]))  # type: ignore[list-item]

    (record,) = chat_events(caplog)
    assert record.levelno == logging.INFO
    assert record.getMessage() == "Chat ok"
    fields = {k: getattr(record, k) for k in (
        "outcome", "question", "standalone_question", "history_messages", "provider",
        "model", "tools", "sources", "answer_chars", "prompt_tokens",
        "completion_tokens", "llm_calls", "cached")}  # fmt: skip
    assert fields == {
        "outcome": "ok",
        "question": "And who won?",
        "standalone_question": "Who won the 1976 title?",
        "history_messages": 2,
        "provider": "groq",
        "model": "openai/gpt-oss-120b",
        "tools": [{"name": "query_stats", "ok": True}],
        "sources": 1,
        "answer_chars": len(ANSWER.text),
        "prompt_tokens": 900,
        "completion_tokens": 80,
        "llm_calls": 2,
        "cached": False,
    }
    assert isinstance(record.latency_ms, int)


@pytest.mark.parametrize(
    ("error", "message", "error_type"),
    [
        (AnswerUnavailableError("All providers failed"), "All providers failed", None),
        (ValueError("query must not be empty"), "query must not be empty", None),
        (RuntimeError("db.internal password=x"), GENERIC_ERROR, "RuntimeError"),
    ],
)
def test_a_failed_answer_logs_an_error_event(
    caplog, error, message, error_type
) -> None:
    list(event_frames(FakeOrchestrator([], error), "q"))

    (record,) = chat_events(caplog)
    assert record.levelno == logging.WARNING
    assert (record.outcome, record.error) == ("error", message)
    assert getattr(record, "error_type", None) == error_type
    assert "password" not in record.error


def test_a_client_that_goes_away_is_logged_as_disconnected(caplog) -> None:
    caplog.set_level(logging.INFO)
    frames = event_frames(FakeOrchestrator(), "q")

    next(frames)
    frames.close()

    (record,) = chat_events(caplog)
    assert record.outcome == "disconnected"
    assert not hasattr(record, "provider")


def test_the_api_writes_chat_feedback_and_rate_limit_events_to_the_file(
    tmp_path: Path,
) -> None:
    log_file = tmp_path / "apexgpt.log"
    app = create_app(make_settings(environment="test", log_file=str(log_file),
                                   rate_limit_chat="1/minute"))  # fmt: skip
    app.dependency_overrides[get_orchestrator] = lambda: FakeOrchestrator()
    app.dependency_overrides[get_session] = lambda: FakeSession()
    client = TestClient(app, client=("203.0.113.9", 4242))

    client.post("/api/chat", json={"question": "How did Hunt win?"})
    client.post("/api/chat", json={"question": "again"})
    client.post("/api/feedback", json=BODY)

    events = [e for e in lines(log_file) if "event" in e]
    assert [(e["event"], e.get("outcome")) for e in events] == [
        ("chat", "ok"),
        ("rate_limited", None),
        ("feedback", "ok"),
    ]
    chat, limited, feedback = events
    assert chat["question"] == "How did Hunt win?" and chat["provider"] == "groq"
    assert (limited["scope"], limited["limit"]) == ("chat", "1 per 1 minute")
    assert (feedback["rating"], feedback["id"]) == ("up", 1)
    assert "203.0.113.9" not in log_file.read_text()  # no client addresses


def test_an_unreadable_log_path_is_left_to_configure_logging(monkeypatch) -> None:
    """Path.is_dir raises PermissionError under a directory we can't read."""

    def denied(self) -> bool:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "is_dir", denied)

    assert make_settings(log_file="/root/no/apexgpt.log").log_file == Path(
        "/root/no/apexgpt.log"
    )
