"""Ask ApexGPT a question from the command line (the Phase 3 done check).

    uv run python -m app.answer "Who has the most wins at Monza?"
    uv run python -m app.answer "Explain Abu Dhabi 2021" --trace

Needs the corpus, the LLM key(s) and READONLY_DATABASE_URL from .env.
"""

import argparse
import json
import sys

from app.answer import AnswerUnavailableError, build_orchestrator
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.retrieval.search import normalise_query


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.answer", description="Ask ApexGPT."
    )
    parser.add_argument("question")
    parser.add_argument(
        "--trace", action="store_true", help="show names, tool calls, timing"
    )
    args = parser.parse_args(argv)
    try:
        normalise_query(args.question)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    settings = get_settings()
    configure_logging("WARNING" if not args.trace else settings.log_level)
    try:
        answer = build_orchestrator(settings).answer(args.question)
    except AnswerUnavailableError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(answer.text)
    if answer.sources:
        print("\nSources:")
        for s in answer.sources:
            where = f"{s.title} > {s.section}" if s.section else s.title
            print(f"  [{s.id}] {where} — {s.url}")
    if args.trace:
        print("\n--- trace ---")
        if answer.resolution and answer.resolution.mentions:
            names = ", ".join(
                f"{m.text}→{m.best.entity.name}" for m in answer.resolution.mentions
            )
            print(f"names: {names}")
        for call in answer.tool_calls:
            status = "ok" if call.ok else f"error: {call.error}"
            print(
                f"tool {call.name} {json.dumps(call.arguments, ensure_ascii=False)} -> {status}"
            )
        print(
            f"{answer.provider} · {answer.model} · {answer.llm_calls} LLM calls · "
            f"{answer.prompt_tokens}+{answer.completion_tokens} tokens · {answer.latency_ms} ms"
        )
    return 0


if __name__ == "__main__":
    sys.exit(run())
