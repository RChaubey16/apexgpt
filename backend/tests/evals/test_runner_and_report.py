"""The eval runner, results files, reports and CLI (F6.2). No LLM or database."""

from pathlib import Path

import pytest

from app.answer import AnswerUnavailableError
from evals import __main__ as cli
from evals.judge import JudgeError
from evals.report import percentile, render_retrieval, render_run
from evals.runner import (
    RESULTS_FILE,
    RetrievalResult,
    RunError,
    RunMeta,
    RunOptions,
    append_result,
    evaluate,
    load_results,
    new_run_dir,
    read_meta,
    retrieval_questions,
    run,
    run_retrieval,
    select,
    write_meta,
)
from evals.scoring import JudgeVerdict, QuestionResult, Status
from tests.evals.fakes import answer, golden_set, question

GOLDEN = golden_set(
    {
        "id": "stats-a",
        "category": "stats",
        "question": "Who has the most wins?",
        "expect": {"answer": ["Hamilton"], "tools": ["query_stats"]},
        "sql": "SELECT 'Hamilton'",
    },
    {
        "id": "races-b",
        "category": "races",
        "question": "Explain Abu Dhabi 2021",
        "expect": {
            "facts": ["late safety car"],
            "sources": ["2021 Abu Dhabi Grand Prix"],
        },
    },
    {
        "id": "oos-c",
        "category": "out_of_scope",
        "question": "Who will win in 2026?",
        "expect": {"behavior": "decline"},
    },
)


class Answerer:
    """Returns scripted answers per question (or raises), records calls."""

    def __init__(self, replies: dict) -> None:
        self.replies = {k: list(v) for k, v in replies.items()}
        self.calls: list[tuple[str, list]] = []

    def __call__(self, text, history):  # noqa: ANN001
        self.calls.append((text, list(history)))
        reply = self.replies[text].pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _judge(behavior_ok: bool = True):  # noqa: ANN202
    calls = []

    def judge(q, observed):  # noqa: ANN001, ANN202
        calls.append(q.id)
        return JudgeVerdict(
            behavior_ok=behavior_ok, facts=("supported",) * len(q.expect.facts)
        )

    judge.calls = calls
    return judge


# --- selection -------------------------------------------------------------------


def test_select() -> None:
    ids = lambda qs: [q.id for q in qs]  # noqa: E731
    assert ids(select(GOLDEN)) == ["stats-a", "races-b", "oos-c"]
    assert ids(select(GOLDEN, categories=["races"])) == ["races-b"]
    assert ids(select(GOLDEN, categories=["races"], ids=["oos-c"])) == [
        "races-b",
        "oos-c",
    ]
    assert ids(select(GOLDEN, limit=2)) == ["stats-a", "races-b"]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"ids": ["nope"]}, "unknown question ids: nope"),
        ({"categories": ["gossip"]}, "unknown categories: gossip"),
        ({"limit": 0}, "at least 1"),
    ],
)
def test_bad_selection(kwargs: dict, message: str) -> None:
    with pytest.raises(RunError, match=message):
        select(GOLDEN, **kwargs)


# --- evaluating one question --------------------------------------------------------


def test_evaluate_scores_and_judges() -> None:
    q = GOLDEN.get("races-b")
    judge = _judge()
    answerer = Answerer(
        {
            q.question: [
                answer("A late safety car…", titles=["2021 Abu Dhabi Grand Prix"])
            ]
        }
    )
    result = evaluate(q, answerer, judge)

    assert result.status is Status.PASS
    assert [c.name for c in result.checks] == ["sources", "behavior", "facts"]
    assert judge.calls == ["races-b"]
    assert result.judge is not None


def test_evaluate_without_a_judge_skips_judged_checks() -> None:
    q = GOLDEN.get("races-b")
    answerer = Answerer({q.question: [answer(titles=["2021 Abu Dhabi Grand Prix"])]})
    result = evaluate(q, answerer, None)
    assert [c.name for c in result.checks] == ["sources"]


def test_a_question_without_judged_expectations_never_calls_the_judge() -> None:
    q = GOLDEN.get("stats-a")
    judge = _judge()
    answerer = Answerer(
        {q.question: [answer("Lewis Hamilton", tools=[("query_stats", True)])]}
    )
    assert evaluate(q, answerer, judge).status is Status.PASS
    assert judge.calls == []


def test_a_judge_error_marks_checks_as_errors() -> None:
    q = GOLDEN.get("oos-c")

    def broken(question, observed):  # noqa: ANN001, ANN202
        raise JudgeError("no JSON")

    result = evaluate(
        q, Answerer({q.question: [answer("I can't predict that.")]}), broken
    )
    assert result.status is Status.ERROR
    assert result.checks[0].detail == "judge failed: no JSON"


def test_unavailable_answers_are_retried_after_a_wait() -> None:
    q = GOLDEN.get("stats-a")
    waits: list[float] = []
    answerer = Answerer(
        {
            q.question: [
                AnswerUnavailableError("All providers are rate limited"),
                answer("Lewis Hamilton", tools=[("query_stats", True)]),
            ]
        }
    )
    result = evaluate(q, answerer, None, retries=1, retry_wait=42, sleep=waits.append)
    assert result.status is Status.PASS
    assert waits == [42]


def test_no_answer_after_retries_is_an_error_result() -> None:
    q = GOLDEN.get("stats-a")
    waits: list[float] = []
    answerer = Answerer({q.question: [AnswerUnavailableError("busy")] * 3})
    result = evaluate(q, answerer, None, retries=2, retry_wait=1, sleep=waits.append)
    assert result.error == "busy"
    assert result.observed is None
    assert waits == [1, 1]  # no wait after the last attempt


def test_a_rejected_question_is_not_retried() -> None:
    q = GOLDEN.get("stats-a")
    answerer = Answerer({q.question: [ValueError("question is too long")]})
    result = evaluate(q, answerer, None, retries=3, sleep=pytest.fail)
    assert result.error == "rejected: question is too long"
    assert len(answerer.calls) == 1


def test_history_is_passed_to_the_pipeline() -> None:
    q = question(
        category="follow_up",
        question="How many did he win?",
        history=[
            {"role": "user", "content": "Who won 1988?"},
            {"role": "assistant", "content": "Senna."},
        ],
        expect={"answer": ["8"]},
    )
    answerer = Answerer({q.question: [answer("8")]})
    evaluate(q, answerer, None)
    history = answerer.calls[0][1]
    assert [(m.role, m.content) for m in history] == [
        ("user", "Who won 1988?"),
        ("assistant", "Senna."),
    ]


# --- runs and results files ------------------------------------------------------------


def _replies(**overrides: object) -> dict:
    replies = {
        "Who has the most wins?": [
            answer("Lewis Hamilton", tools=[("query_stats", True)])
        ],
        "Explain Abu Dhabi 2021": [answer("…", titles=["2021 Abu Dhabi Grand Prix"])],
        "Who will win in 2026?": [answer("I can't say.")],
    }
    replies.update(overrides)
    return replies


def test_run_writes_one_line_per_question(tmp_path: Path) -> None:
    lines: list[str] = []
    results = run(
        GOLDEN.questions,
        tmp_path,
        Answerer(_replies()),
        _judge(),
        progress=lines.append,
    )
    assert [r.status for r in results] == [Status.PASS] * 3
    assert len((tmp_path / RESULTS_FILE).read_text().splitlines()) == 3
    assert set(load_results(tmp_path)) == {"stats-a", "races-b", "oos-c"}
    assert lines[0] == "[1/3] PASS  stats-a"


def test_run_reports_failures_in_progress(tmp_path: Path) -> None:
    lines: list[str] = []
    replies = _replies(**{"Who has the most wins?": [answer("Schumacher")]})
    run(GOLDEN.questions[:1], tmp_path, Answerer(replies), None, progress=lines.append)
    assert lines == ["[1/1] FAIL  stats-a  (answer, tools)"]


def test_resume_skips_done_questions_and_retries_errors(tmp_path: Path) -> None:
    first = Answerer(
        _replies(**{"Explain Abu Dhabi 2021": [AnswerUnavailableError("busy")] * 2})
    )
    run(
        GOLDEN.questions,
        tmp_path,
        first,
        _judge(),
        RunOptions(retry_wait=0),
        progress=print,
    )
    assert load_results(tmp_path)["races-b"].error == "busy"

    second = Answerer(_replies())
    lines: list[str] = []
    results = run(GOLDEN.questions, tmp_path, second, _judge(), progress=lines.append)

    assert [text for text, _ in second.calls] == ["Explain Abu Dhabi 2021"]
    assert lines[0] == "Resuming: 2 done, 1 to go"
    assert [r.status for r in results] == [Status.PASS] * 3
    # The retry is appended; the latest line wins.
    assert len((tmp_path / RESULTS_FILE).read_text().splitlines()) == 4
    assert load_results(tmp_path)["races-b"].error is None


def test_delay_between_questions(tmp_path: Path) -> None:
    waits: list[float] = []
    run(
        GOLDEN.questions,
        tmp_path,
        Answerer(_replies()),
        _judge(),
        RunOptions(delay=5),
        sleep=waits.append,
        progress=lambda _: None,
    )
    assert waits == [5, 5]


def test_corrupt_results_file(tmp_path: Path) -> None:
    (tmp_path / RESULTS_FILE).write_text('{"id": "x"}\nnot json\n')
    with pytest.raises(RunError, match="results.jsonl:1 is not a valid result"):
        load_results(tmp_path)


def test_blank_lines_and_a_missing_file(tmp_path: Path) -> None:
    assert load_results(tmp_path) == {}
    append_result(tmp_path, QuestionResult(id="a", category="races", question="?"))
    with (tmp_path / RESULTS_FILE).open("a") as f:
        f.write("\n")
    assert list(load_results(tmp_path)) == ["a"]


def _meta(**overrides: object) -> RunMeta:
    values = {
        "started_at": "2026-11-25T10:00:00+00:00",
        "git_commit": "abc1234",
        "golden_sha256": "f" * 64,
        "provider": "groq",
        "judge_provider": None,
        "judge": True,
        "question_ids": ("stats-a",),
    }
    values.update(overrides)
    return RunMeta(**values)


def test_meta_round_trip_and_run_dirs(tmp_path: Path) -> None:
    run_dir = new_run_dir(tmp_path, "baseline")
    assert run_dir.name.endswith("Z-baseline")
    assert read_meta(run_dir) is None
    write_meta(run_dir, _meta())
    assert read_meta(run_dir) == _meta()
    (run_dir / "meta.json").write_text("{}")
    with pytest.raises(RunError, match="cannot read"):
        read_meta(run_dir)


# --- reports ---------------------------------------------------------------------------


def test_percentile() -> None:
    assert percentile([], 50) is None
    assert percentile([5], 95) == 5
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 50) == 5
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 95) == 10


def test_render_run(tmp_path: Path) -> None:
    replies = _replies(
        **{
            "Who has the most wins?": [answer("Schumacher | 91", provider="gemini")],
            "Who will win in 2026?": [AnswerUnavailableError("busy")] * 2,
        }
    )
    results = run(
        GOLDEN.questions,
        tmp_path,
        Answerer(replies),
        _judge(),
        RunOptions(retry_wait=0),
        progress=lambda _: None,
    )
    report = render_run(results, _meta())

    assert "**1/3 passed (33%)**, 1 with errors" in report
    assert "- Answer provider: groq · judge: fallback chain" in report
    assert "| races | 1 | 1 | 0 | 0 | 100% |" in report
    assert "| stats | 1 | 0 | 1 | 0 | 0% |" in report
    assert "| answer | 1 | 0 | 1 | 0 | 0% |" in report
    assert "| gemini · gemini-model | 1 | 0 | 1 | 0 | 0% |" in report
    assert "| (none) | 1 | 0 | 0 | 1 | 0% |" in report
    assert "### `stats-a` (stats): fail" in report
    assert "- **answer** fail: missing ['Hamilton']" in report
    assert "- Answer: Schumacher \\| 91" in report  # table pipes escaped
    assert "### `oos-c` (out_of_scope): error" in report
    assert "- Error: busy" in report
    assert "latency p50 1000 ms" in report
    assert "Tokens: 7,000 for answers (3,500 each)" in report


def test_render_run_with_nothing() -> None:
    assert "**0/0 passed (–)**" in render_run([])


def test_long_answers_are_cut_in_the_report(tmp_path: Path) -> None:
    long = "word " * 200
    results = run(
        GOLDEN.questions[:1],
        tmp_path,
        Answerer({"Who has the most wins?": [answer(long)]}),
        None,
        progress=lambda _: None,
    )
    line = next(
        x for x in render_run(results).splitlines() if x.startswith("- Answer:")
    )
    assert line.endswith(" …")
    assert len(line) < 320


def test_retrieval_questions_and_report() -> None:
    golden = golden_set(
        {
            "id": "a",
            "category": "races",
            "question": "Explain Abu Dhabi 2021",
            "expect": {"facts": ["f"], "sources": ["2021 Abu Dhabi Grand Prix"]},
        },
        {
            "id": "b",
            "category": "races",
            "question": "Who won Monaco 1984?",
            "expect": {"facts": ["f"], "sources": ["1984 Monaco Grand Prix"]},
        },
        {
            "id": "c",
            "category": "follow_up",
            "question": "And then?",
            "history": [{"role": "user", "content": "Tell me about 1976"}],
            "expect": {"facts": ["f"], "sources": ["1976 Formula One season"]},
        },
        {
            "id": "d",
            "category": "stats",
            "question": "Most wins?",
            "expect": {"answer": ["x"]},
        },
    )
    assert [q.id for q in retrieval_questions(golden.questions)] == ["a", "b"]

    found = {
        "Explain Abu Dhabi 2021": ["Safety car", "2021 Abu Dhabi Grand Prix"],
        "Who won Monaco 1984?": ["1984 French Grand Prix"],
    }
    results = run_retrieval(golden.questions, lambda query: found[query])
    assert [r.rank for r in results] == [2, None]

    report = render_retrieval(results, 5, True)
    assert "**1/2 found an expected article (50%), MRR 0.25**" in report
    assert "| `a` | races | 2 | Safety car, 2021 Abu Dhabi Grand Prix |" in report
    assert "- `b`: expected ['1984 Monaco Grand Prix']" in report
    assert (
        RetrievalResult(
            id="x", category="races", query="q", expected=("A",), retrieved=()
        ).rank
        is None
    )


# --- CLI ---------------------------------------------------------------------------------


def test_cli_list(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "stats (" in out
    assert "  races-abu-dhabi-2021: Explain Abu Dhabi 2021" in out


def test_cli_bad_selection_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["run", "--id", "nope"]) == 2
    assert "unknown question ids: nope" in capsys.readouterr().err


def test_cli_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["report", str(tmp_path)]) == 2
    assert "no results" in capsys.readouterr().err

    write_meta(tmp_path, _meta())
    run(
        GOLDEN.questions[:1],
        tmp_path,
        Answerer(_replies()),
        None,
        progress=lambda _: None,
    )
    assert cli.main(["report", str(tmp_path)]) == 0
    assert "**1/1 passed (100%)**" in (tmp_path / "report.md").read_text()


def test_cli_resume_needs_a_run_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["run", "--resume", str(tmp_path)]) == 2
    assert "not an eval run" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], ("groq", None, False)),
        (
            ["--provider", "gemini", "--judge-provider", "groq"],
            ("gemini", "groq", False),
        ),
        (["--no-judge"], ("groq", None, True)),
    ],
)
def test_resume_keeps_the_runs_providers(argv: list[str], expected: tuple) -> None:
    args = cli.build_parser().parse_args(["run", "--resume", "x", *argv])
    cli.keep_run_settings(args, _meta())
    assert (args.provider, args.judge_provider, args.no_judge) == expected

    args = cli.build_parser().parse_args(["run", "--resume", "x"])
    cli.keep_run_settings(args, _meta(judge=False, judge_provider="gemini"))
    assert (args.judge_provider, args.no_judge) == ("gemini", True)


@pytest.mark.parametrize(
    "argv",
    [
        ["run", "--provider", "openai"],
        ["run", "--delay", "-1"],
        ["run", "--retries", "9"],
        ["run", "--resume", "x", "--label", "y"],
        ["retrieval", "--k", "0"],
    ],
)
def test_cli_rejects_bad_arguments(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as info:
        cli.main(argv)
    assert info.value.code == 2
