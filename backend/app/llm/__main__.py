"""Ask the configured LLM providers a question from the command line.

    uv run python -m app.llm "Who won the 1976 championship?"
    uv run python -m app.llm "Explain DRS" --stream
    uv run python -m app.llm "Hi" --provider groq     # only this provider

Uses GROQ_API_KEY / GEMINI_API_KEY / OPENROUTER_API_KEY from the environment or
.env. Prints which provider answered, then the answer.
"""

import argparse
import sys
import time

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.llm import build_llm_client
from app.llm.client import MAX_TOKENS_LIMIT
from app.llm.errors import LLMError

PROVIDERS = ("groq", "gemini", "openrouter")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.llm", description="Ask the configured LLM providers."
    )
    parser.add_argument("prompt", help="the question")
    parser.add_argument("--provider", choices=PROVIDERS, help="use only this provider")
    parser.add_argument("--stream", action="store_true", help="stream the answer")
    parser.add_argument(
        "--max-tokens", type=int, default=512, help=f"1–{MAX_TOKENS_LIMIT}"
    )
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    client = build_llm_client(settings, only=args.provider)
    if not client.provider_names:
        wanted = args.provider or "any provider"
        print(f"error: no API key configured for {wanted}", file=sys.stderr)
        return 2
    messages = [{"role": "user", "content": args.prompt}]
    try:
        started = time.perf_counter()
        if args.stream:
            stream = client.stream(messages, max_tokens=args.max_tokens)
            print(f"[{stream.provider} · {stream.model}]", flush=True)
            for piece in stream:
                print(piece, end="", flush=True)
            print(f"\n\n({time.perf_counter() - started:.1f}s)")
        else:
            response = client.complete(messages, max_tokens=args.max_tokens)
            tokens = (
                f", {response.usage.prompt_tokens}+{response.usage.completion_tokens} tokens"
                if response.usage
                else ""
            )
            print(
                f"[{response.provider} · {response.model} · "
                f"{response.latency_ms} ms{tokens}]\n"
            )
            print(response.content or "")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except LLMError as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run())
