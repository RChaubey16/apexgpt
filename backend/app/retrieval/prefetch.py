"""Download and check both search models into a directory (F7.1).

    python -m app.retrieval.prefetch /app/models

The production image runs this at build time, so a new container never
downloads ~145 MB on its first question (and runs with HF_HUB_OFFLINE=1). It
loads the models through the app's own classes and uses each once, so the image
holds exactly what the app will load.
"""

import argparse
import sys
from pathlib import Path

from app.retrieval.embedder import DIMENSIONS, FastEmbedQueryEmbedder
from app.retrieval.errors import SearchError
from app.retrieval.reranker import FastEmbedReranker


def prefetch(cache_dir: Path) -> None:
    """Load both models into ``cache_dir``; raises SearchError if one fails."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    vector = FastEmbedQueryEmbedder(cache_dir).embed_query("Who won in 1976?")
    if len(vector) != DIMENSIONS:
        raise SearchError(f"the embedder returned {len(vector)} dimensions")
    scores = FastEmbedReranker(cache_dir).score("Who won in 1976?", ["James Hunt"])
    if len(scores) != 1:
        raise SearchError("the reranker returned no score")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.retrieval.prefetch")
    parser.add_argument("cache_dir", type=Path)
    args = parser.parse_args(argv)
    try:
        prefetch(args.cache_dir)
    except SearchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Search models ready in {args.cache_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
