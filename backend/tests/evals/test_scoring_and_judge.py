"""Scoring checks and the LLM judge (F6.2)."""

import json

import pytest

from app.llm import LLMUnavailableError
from evals.judge import JUDGE_PROMPT, Judge, JudgeError, judge_message, parse_verdict
from evals.scoring import (
    JudgeVerdict,
    Observed,
    QuestionResult,
    Status,
    check_answer,
    check_judgement,
    needs_judge,
)
from tests.evals.fakes import ReplyingLLM, answer, question


def _observed(**kwargs: object) -> Observed:
    return Observed.from_answer(answer(**kwargs))


def _by_name(checks) -> dict:  # noqa: ANN001
    return {c.name: c for c in checks}


# --- Observed ----------------------------------------------------------------


def test_observed_keeps_what_scoring_needs() -> None:
    obs = _observed(
        tools=[("query_stats", True), ("search_f1_knowledge", False)],
        titles=["A", "B", "A"],
    )
    assert [(t.name, t.ok) for t in obs.tools] == [
        ("query_stats", True),
        ("search_f1_knowledge", False),
    ]
    assert obs.cited_titles == ("A", "B")  # each article once, in order
    assert (obs.provider, obs.prompt_tokens, obs.llm_calls) == ("groq", 3000, 2)
    assert Observed.model_validate_json(obs.model_dump_json()) == obs


# --- checks without the LLM ------------------------------------------------------


def test_answer_values_pass_and_fail() -> None:
    q = question(expect={"answer": ["Nelson Piquet", "Benetton"]})
    ok = _by_name(check_answer(q, _observed(text="Nelson Piquet won for Benetton.")))
    assert ok["answer"].status is Status.PASS
    bad = _by_name(check_answer(q, _observed(text="Nelson Piquet won.")))
    assert bad["answer"].status is Status.FAIL
    assert "Benetton" in bad["answer"].detail


def test_tools_must_be_called_successfully() -> None:
    q = question(expect={"answer": ["x"], "tools": ["query_stats"]}, sql="SELECT 'x'")
    used = _by_name(check_answer(q, _observed(text="x", tools=[("query_stats", True)])))
    assert used["tools"].status is Status.PASS

    failed = _by_name(
        check_answer(q, _observed(text="x", tools=[("query_stats", False)]))
    )
    assert failed["tools"].status is Status.FAIL
    assert "failed calls: ['query_stats']" in failed["tools"].detail

    retried = _by_name(
        check_answer(
            q,
            _observed(text="x", tools=[("query_stats", False), ("query_stats", True)]),
        )
    )
    assert retried["tools"].status is Status.PASS
    assert retried["tools"].detail == ""

    none = _by_name(check_answer(q, _observed(text="x")))
    assert none["tools"].detail == "not used: ['query_stats']"


def test_one_expected_source_is_enough() -> None:
    q = question(expect={"facts": ["f"], "sources": ["A", "B"]})
    assert (
        _by_name(check_answer(q, _observed(titles=["C", "B"])))["sources"].status
        is Status.PASS
    )
    miss = _by_name(check_answer(q, _observed(titles=["C"])))["sources"]
    assert miss.status is Status.FAIL
    assert "expected one of ['A', 'B']" in miss.detail
    assert "cited nothing" in _by_name(check_answer(q, _observed()))["sources"].detail


def test_standalone_checks_the_rewrite_not_the_answer() -> None:
    q = question(
        category="follow_up",
        question="How many did he win?",
        history=[{"role": "user", "content": "Who won in 1988?"}],
        expect={"answer": ["8"], "standalone": ["Senna", "1988"]},
    )
    good = _observed(
        text="8 wins", question_text="How many races did Ayrton Senna win in 1988?"
    )
    assert _by_name(check_answer(q, good))["standalone"].status is Status.PASS
    clarifying = _observed(
        text="Senna in 1988: 8",
        question_text="Could you specify which driver you mean?",
    )
    check = _by_name(check_answer(q, clarifying))["standalone"]
    assert check.status is Status.FAIL
    assert "Could you specify" in check.detail


def test_only_expected_checks_are_applied() -> None:
    q = question(expect={"facts": ["f"]})
    assert check_answer(q, _observed()) == []


@pytest.mark.parametrize(
    ("expect", "judged"),
    [
        ({"answer": ["x"]}, False),
        ({"facts": ["f"]}, True),
        ({"behavior": "decline"}, True),
    ],
)
def test_needs_judge(expect: dict, judged: bool) -> None:
    category = "out_of_scope" if expect.get("behavior") == "decline" else "races"
    assert needs_judge(question(category=category, expect=expect)) is judged


# --- judgement checks ---------------------------------------------------------------


def _verdict(behavior_ok: bool = True, *facts: str) -> JudgeVerdict:
    return JudgeVerdict(behavior_ok=behavior_ok, facts=facts, reason="r")


def test_judgement_checks() -> None:
    q = question(expect={"facts": ["one", "two"]})
    checks = _by_name(check_judgement(q, _verdict(True, "supported", "supported")))
    assert {n: c.status for n, c in checks.items()} == {
        "behavior": Status.PASS,
        "facts": Status.PASS,
    }
    checks = _by_name(check_judgement(q, _verdict(False, "supported", "contradicted")))
    assert checks["behavior"].status is Status.FAIL
    assert checks["behavior"].detail == "r"
    assert checks["facts"].detail == "two (contradicted)"
    checks = _by_name(check_judgement(q, _verdict(True, "missing", "supported")))
    assert checks["facts"].status is Status.FAIL
    assert checks["facts"].detail == "one (missing)"


def test_judgement_without_facts_checks_behavior_only() -> None:
    q = question(category="out_of_scope", expect={"behavior": "decline"})
    assert [c.name for c in check_judgement(q, _verdict(True))] == ["behavior"]


def test_a_failed_judge_is_an_error_not_a_fail() -> None:
    q = question(expect={"facts": ["one"]})
    checks = check_judgement(q, None, "no JSON")
    assert {c.status for c in checks} == {Status.ERROR}
    assert all("judge failed: no JSON" in c.detail for c in checks)


def test_question_status() -> None:
    def result(*statuses: Status, error: str | None = None) -> QuestionResult:
        from evals.scoring import CheckResult

        return QuestionResult(
            id="q",
            category="races",
            question="?",
            checks=tuple(
                CheckResult(name=f"c{i}", status=s) for i, s in enumerate(statuses)
            ),
            error=error,
        )

    assert result(Status.PASS, Status.PASS).status is Status.PASS
    assert result(Status.PASS, Status.ERROR).status is Status.ERROR
    assert result(Status.ERROR, Status.FAIL).status is Status.FAIL
    assert result(error="no answer").status is Status.ERROR


# --- the judge -------------------------------------------------------------------


def _reply(
    behavior_ok: bool = True, facts=("supported",), reason="ok"
) -> str:  # noqa: ANN001
    return json.dumps(
        {"behavior_ok": behavior_ok, "facts": list(facts), "reason": reason}
    )


def test_judge_asks_for_json_and_returns_a_verdict() -> None:
    llm = ReplyingLLM("Here you go:\n" + _reply(True, ["supported", "missing"]))
    q = question(expect={"facts": ["Piquet won", "Moreno second"]})
    verdict = Judge(llm)(q, _observed())

    assert verdict.behavior_ok is True
    assert verdict.facts == ("supported", "missing")
    assert (verdict.provider, verdict.prompt_tokens) == ("gemini", 800)
    assert llm.kwargs[0]["temperature"] == 0.0
    system, user = llm.messages[0]
    assert system["content"] == JUDGE_PROMPT
    assert "1. Piquet won\n2. Moreno second" in user["content"]
    assert "<answer>\nNelson Piquet won it.\n</answer>" in user["content"]


def test_judge_message_for_a_follow_up_and_a_decline() -> None:
    q = question(
        category="follow_up",
        question="Which team?",
        history=[
            {"role": "user", "content": "Who won 2009?"},
            {"role": "assistant", "content": "Button."},
        ],
        expect={"answer": ["Brawn"], "standalone": ["Button"]},
    )
    text = judge_message(q, _observed(question_text="Which team did Button drive for?"))
    assert "user: Who won 2009?\nassistant: Button." in text
    assert "(Understood as: Which team did Button drive for?)" in text
    assert "give an empty list" in text

    decline = question(category="out_of_scope", expect={"behavior": "decline"})
    assert "Expected behavior: decline" in judge_message(decline, _observed())


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (None, "returned nothing"),
        ("", "returned nothing"),
        ("I think it is fine.", "no JSON object"),
        ('{"behavior_ok": "maybe", "facts": []}', "invalid"),
        ('{"behavior_ok": true, "facts": ["probably"]}', "invalid"),
        ('{"behavior_ok": true, "facts": [}', "invalid"),
        ('{"behavior_ok": true, "facts": []}', "0 fact verdicts for 1 facts"),
    ],
)
def test_unusable_verdicts(content: str | None, message: str) -> None:
    with pytest.raises(JudgeError, match=message):
        parse_verdict(content, 1)


def test_judge_wraps_llm_failures_after_retrying() -> None:
    llm = ReplyingLLM(*[LLMUnavailableError("All providers failed")] * 3)
    waits: list[float] = []
    judge = Judge(llm, retries=2, retry_wait=30, sleep=waits.append)
    with pytest.raises(JudgeError, match="no judge available"):
        judge(question(expect={"facts": ["f"]}), _observed())
    assert waits == [30, 30]
    assert len(llm.messages) == 3


def test_a_busy_judge_is_waited_for() -> None:
    llm = ReplyingLLM(LLMUnavailableError("rate limited"), _reply(True, ["supported"]))
    waits: list[float] = []
    verdict = Judge(llm, retry_wait=5, sleep=waits.append)(
        question(expect={"facts": ["f"]}), _observed()
    )
    assert verdict.facts == ("supported",)
    assert waits == [5]
