"""Evaluate ApexGPT against the golden set (F6.2).

    uv run python -m evals list                                   # categories and ids
    uv run python -m evals run --category stats --provider groq   # spends LLM quota
    uv run python -m evals run --id races-abu-dhabi-2021 --id trick-monaco-2020
    uv run python -m evals run --resume ../data/eval/runs/<run>   # continue a run
    uv run python -m evals report ../data/eval/runs/<run>         # re-render report.md
    uv run python -m evals rescore ../data/eval/runs/<run>        # same answers, current golden set
    uv run python -m evals retrieval                              # no LLM; top-5 check

Needs the loaded corpus, READONLY_DATABASE_URL and LLM keys from .env, like
`python -m app.answer`. Results go to data/eval/runs/ (git-ignored).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from app.retrieval.retriever import CANDIDATES, TOP_K
from evals.golden import DEFAULT_PATH, GoldenSetError, load_golden_set
from evals.report import render_retrieval, render_run
from evals.runner import (
    REPORT_FILE,
    RUNS_DIR,
    RunError,
    RunMeta,
    RunOptions,
    file_sha256,
    git_commit,
    load_results,
    new_run_dir,
    read_meta,
    rescore,
    run,
    run_retrieval,
    select,
    write_meta,
)

PROVIDERS = ("groq", "gemini", "openrouter")


def _positive(value: str) -> float:
    number = float(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be 0 or more")
    return number


def _add_selection(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--category", action="append", default=[], help="repeatable")
    parser.add_argument(
        "--id", action="append", default=[], dest="ids", help="repeatable"
    )
    parser.add_argument("--limit", type=int, help="at most this many questions")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evals", description="Evaluate ApexGPT on the golden set."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("list", help="show the golden questions")

    run_p = commands.add_parser("run", help="answer and score questions (uses LLMs)")
    _add_selection(run_p)
    run_p.add_argument("--provider", choices=PROVIDERS, help="answer with only this")
    run_p.add_argument(
        "--judge-provider", choices=PROVIDERS, help="judge with only this"
    )
    run_p.add_argument("--no-judge", action="store_true", help="skip facts/behavior")
    run_p.add_argument(
        "--delay", type=_positive, default=0.0, help="seconds between questions"
    )
    run_p.add_argument(
        "--retry-wait",
        type=_positive,
        default=60.0,
        help="seconds to wait before retrying a question no provider answered",
    )
    run_p.add_argument("--retries", type=int, default=1, choices=range(0, 4))
    where = run_p.add_mutually_exclusive_group()
    where.add_argument("--resume", type=Path, help="continue the run in this directory")
    where.add_argument("--label", help="suffix for the new run's directory name")

    rescore_p = commands.add_parser(
        "rescore", help="score a run's answers again with the current golden set"
    )
    rescore_p.add_argument("run_dir", type=Path)
    rescore_p.add_argument("--judge-provider", choices=PROVIDERS)
    rescore_p.add_argument("--no-judge", action="store_true")
    rescore_p.add_argument("--label", default="rescored")

    report_p = commands.add_parser("report", help="re-render a run's report")
    report_p.add_argument("run_dir", type=Path)

    retrieval_p = commands.add_parser(
        "retrieval", help="top-k retrieval check (no LLM)"
    )
    _add_selection(retrieval_p)
    retrieval_p.add_argument("--no-rerank", action="store_true")
    retrieval_p.add_argument(
        "--k",
        type=int,
        default=TOP_K,
        choices=range(1, CANDIDATES + 1),
        help=f"results to check (1–{CANDIDATES}, the reranker's candidates)",
    )
    return parser


def keep_run_settings(args: argparse.Namespace, meta: RunMeta) -> None:
    """A resumed run keeps the providers and judge it started with, so its
    results stay comparable; options given again still win."""
    args.provider = args.provider or meta.provider
    args.judge_provider = args.judge_provider or meta.judge_provider
    args.no_judge = args.no_judge or not meta.judge


def _list(golden) -> int:  # noqa: ANN001
    for category, questions in golden.by_category().items():
        print(f"{category.value} ({len(questions)})")
        for q in questions:
            print(f"  {q.id}: {q.question}")
    print(f"\n{len(golden.questions)} questions")
    return 0


def build_judge(settings, provider: str | None):  # noqa: ANN001, ANN201
    """(Judge, provider name), pinned to one provider: the one asked for, else
    the first configured one. (None, name) when that provider has no key."""
    from app.llm import build_llm_client, providers_from_settings
    from evals.judge import Judge

    if provider is None:
        configured = providers_from_settings(settings)
        if not configured:
            return None, None
        provider = configured[0].name
    llm = build_llm_client(settings, only=provider)
    if not llm.provider_names:
        return None, provider
    return Judge(llm), provider


def _run(args: argparse.Namespace, golden) -> int:  # noqa: ANN001
    # Imported here: building the pipeline loads settings and the app modules.
    from app.answer import build_orchestrator
    from app.core.config import get_settings
    from app.core.logging import configure_logging
    from app.llm import build_llm_client

    questions = select(golden, categories=args.category, ids=args.ids, limit=args.limit)
    if args.resume:
        run_dir = args.resume
        meta = read_meta(run_dir)
        if meta is None:
            raise RunError(f"{run_dir} is not an eval run (no meta.json)")
        if not (args.category or args.ids or args.limit):
            wanted = set(meta.question_ids)
            questions = [q for q in golden.questions if q.id in wanted]
        keep_run_settings(args, meta)

    settings = get_settings()
    configure_logging("WARNING")
    # A cached answer would score the cache, not the pipeline.
    settings = settings.model_copy(update={"answer_cache_size": 0})
    llm = build_llm_client(settings, only=args.provider)
    if not llm.provider_names:
        print(
            f"error: no key configured for {args.provider or 'any provider'}",
            file=sys.stderr,
        )
        return 1
    judge = None
    if not args.no_judge:
        judge, args.judge_provider = build_judge(settings, args.judge_provider)
        if judge is None:
            print(
                f"error: no key configured for judge {args.judge_provider or 'provider'}",
                file=sys.stderr,
            )
            return 1

    if not args.resume:
        run_dir = new_run_dir(RUNS_DIR, args.label)
        meta = RunMeta(
            started_at=datetime.now(UTC).isoformat(timespec="seconds"),
            git_commit=git_commit(),
            golden_sha256=file_sha256(DEFAULT_PATH),
            provider=args.provider,
            judge_provider=args.judge_provider,
            judge=not args.no_judge,
            question_ids=tuple(q.id for q in questions),
        )
        write_meta(run_dir, meta)

    print(f"Run: {run_dir}  (judge: {args.judge_provider if judge else 'off'})")
    print(f"{len(questions)} questions; ~4–8k tokens per answer, ~1k per judgement")
    orchestrator = build_orchestrator(settings, llm=llm)
    try:
        results = run(
            questions,
            run_dir,
            orchestrator.answer,
            judge,
            RunOptions(
                retries=args.retries, retry_wait=args.retry_wait, delay=args.delay
            ),
        )
    finally:
        orchestrator.close()
    report = render_run(results, meta)
    (run_dir / REPORT_FILE).write_text(report, encoding="utf-8")
    print()
    print(report.split("\n## ")[0].strip())
    print(f"\nReport: {run_dir / REPORT_FILE}")
    return 0


def _rescore(args: argparse.Namespace, golden) -> int:  # noqa: ANN001
    from app.core.config import get_settings
    from app.core.logging import configure_logging

    meta = read_meta(args.run_dir)
    previous = load_results(args.run_dir)
    if meta is None or not previous:
        raise RunError(f"{args.run_dir} is not an eval run with results")
    judge = None
    if not args.no_judge:
        configure_logging("WARNING")
        judge, args.judge_provider = build_judge(get_settings(), args.judge_provider)
        if judge is None:
            print(
                f"error: no key configured for judge {args.judge_provider or 'provider'}",
                file=sys.stderr,
            )
            return 1

    run_dir = args.run_dir.with_name(f"{args.run_dir.name}-{args.label}")
    run_dir.mkdir(exist_ok=False)
    new_meta = meta.model_copy(
        update={
            "golden_sha256": file_sha256(DEFAULT_PATH),
            "judge": judge is not None,
            "judge_provider": args.judge_provider,
        }
    )
    write_meta(run_dir, new_meta)
    print(f"Rescoring {args.run_dir} into {run_dir}")
    results = rescore(previous, golden.questions, run_dir, judge)
    report = render_run(results, new_meta)
    (run_dir / REPORT_FILE).write_text(report, encoding="utf-8")
    print()
    print(report.split("\n## ")[0].strip())
    print(f"\nReport: {run_dir / REPORT_FILE}")
    return 0


def _report(args: argparse.Namespace, golden) -> int:  # noqa: ANN001
    meta = read_meta(args.run_dir)
    results = load_results(args.run_dir)
    if not results:
        raise RunError(f"no results in {args.run_dir}")
    order = {q.id: i for i, q in enumerate(golden.questions)}
    ordered = sorted(results.values(), key=lambda r: order.get(r.id, len(order)))
    report = render_run(ordered, meta)
    (args.run_dir / REPORT_FILE).write_text(report, encoding="utf-8")
    print(report)
    return 0


def _retrieval(args: argparse.Namespace, golden) -> int:  # noqa: ANN001
    from sqlalchemy.orm import sessionmaker

    from app.core.config import get_settings
    from app.core.logging import configure_logging
    from app.db.session import create_db_engine
    from app.retrieval import build_retriever
    from app.retrieval.errors import SearchError

    questions = select(golden, categories=args.category, ids=args.ids, limit=args.limit)
    settings = get_settings()
    configure_logging("WARNING")
    retriever = build_retriever(settings, rerank=not args.no_rerank)
    engine = create_db_engine(settings)
    session_factory = sessionmaker(bind=engine)

    def retrieve(query: str) -> list[str]:
        with session_factory() as session:
            return [r.title for r in retriever.retrieve(session, query, top_k=args.k)]

    try:
        results = run_retrieval(questions, retrieve)
    except SearchError as exc:
        raise RunError(f"search failed: {exc}") from exc
    finally:
        engine.dispose()
    print(render_retrieval(results, args.k, not args.no_rerank))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        golden = load_golden_set()
        if args.command == "list":
            return _list(golden)
        if args.command == "run":
            return _run(args, golden)
        if args.command == "report":
            return _report(args, golden)
        if args.command == "rescore":
            return _rescore(args, golden)
        return _retrieval(args, golden)
    except (GoldenSetError, RunError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
