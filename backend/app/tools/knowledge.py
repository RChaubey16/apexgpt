"""The `search_f1_knowledge` tool: hybrid search + reranking over the Wikipedia
corpus, for "what happened / why / how" questions (F3.6).

    tool = build_knowledge_tool(settings, session_factory)
    outcome = tool.call({"query": "Senna Prost Suzuka collision", "seasons": [1989]})

The model's arguments are validated (it may send anything). The top 5 chunks
come back with source ids S1, S2, … for citations; the orchestrator passes
`first_source_number` so ids stay unique across several searches in one answer.
Chunk text is capped at 2,000 characters (the 99th percentile is ~2,030), so
five results are ~1,600 tokens: the free tier's per-minute limit matters.
"""

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.retrieval import build_retriever
from app.retrieval.errors import SearchError
from app.retrieval.filters import FIRST_SEASON, LAST_SEASON, MAX_SEASONS, SearchFilters
from app.retrieval.retriever import KnowledgeRetriever
from app.retrieval.search import SearchResult
from app.tools.base import Source, ToolOutcome

logger = logging.getLogger(__name__)

NAME = "search_f1_knowledge"
TOP_K = 5
MAX_QUERY_CHARS = 300
MAX_TEXT_CHARS = 2000


class InvalidArguments(ValueError):
    """The model's arguments can't be used; the message is for the model."""


def parse_arguments(arguments: Any) -> tuple[str, SearchFilters | None]:
    """(query, filters) from the model's arguments. Unknown keys are ignored."""
    if not isinstance(arguments, dict):
        raise InvalidArguments("arguments must be an object with a 'query'")
    query = arguments.get("query")
    if not isinstance(query, str) or not query.strip():
        raise InvalidArguments("'query' must be non-empty search terms")
    query = " ".join(query.split())
    if len(query) > MAX_QUERY_CHARS:
        raise InvalidArguments(
            f"'query' must be at most {MAX_QUERY_CHARS} characters of search terms"
        )
    seasons = arguments.get("seasons")
    if seasons is None or seasons == []:
        return query, None  # years in the query still become a filter
    if not isinstance(seasons, list) or not all(
        isinstance(s, int) and not isinstance(s, bool) for s in seasons
    ):
        raise InvalidArguments("'seasons' must be a list of years, e.g. [1988, 1989]")
    if any(not FIRST_SEASON <= s <= LAST_SEASON for s in seasons):
        raise InvalidArguments(
            f"ApexGPT covers the {FIRST_SEASON}–{LAST_SEASON} seasons; "
            "drop seasons outside them"
        )
    if len(set(seasons)) > MAX_SEASONS:
        raise InvalidArguments(
            f"at most {MAX_SEASONS} seasons; leave it out for a wide search"
        )
    return query, SearchFilters(seasons=tuple(seasons))


def _cut(text: str) -> str:
    return text if len(text) <= MAX_TEXT_CHARS else text[:MAX_TEXT_CHARS].rstrip() + "…"


class KnowledgeTool:
    name = NAME

    def __init__(
        self,
        retriever: KnowledgeRetriever,
        session_factory: Callable[[], Session],
        *,
        top_k: int = TOP_K,
    ) -> None:
        self._retriever = retriever
        self._session_factory = session_factory
        self._top_k = top_k

    def definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": NAME,
                "description": (
                    "Search Formula 1 history from Wikipedia (1950-2025): races, "
                    "seasons, drivers, teams, circuits, rivalries, crashes, "
                    "controversies and rules. Returns the most relevant passages, "
                    "each with a source id (S1, S2, ...) to cite. Use it for what "
                    "happened, why and how; use query_stats for numbers and records."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": (
                                "Short search terms: names, race or event, year "
                                "(e.g. 'Senna Prost Suzuka 1989 collision'), "
                                "not the user's whole question."
                            ),
                        },
                        "seasons": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": (
                                "Optional: only these seasons (articles about "
                                "people and teams are always included)."
                            ),
                        },
                    },
                    "required": ["query"],
                },
            },
        }

    def search(
        self, query: str, filters: SearchFilters | None = None
    ) -> list[SearchResult]:
        with self._session_factory() as session:
            return self._retriever.retrieve(
                session, query, filters=filters, top_k=self._top_k
            )

    def call(self, arguments: Any, *, first_source_number: int = 1) -> ToolOutcome:
        try:
            query, filters = parse_arguments(arguments)
            results = self.search(query, filters)
        except (InvalidArguments, ValueError) as exc:
            logger.info("Knowledge search arguments rejected: %s", exc)
            return ToolOutcome.error(NAME, str(exc))
        except SearchError as exc:  # already logged, message is safe
            return ToolOutcome.error(NAME, str(exc))

        if not results:
            return ToolOutcome(
                NAME,
                {
                    "results": [],
                    "note": "nothing relevant found; try other search terms",
                },
                ok=True,
            )
        sources = tuple(
            Source(
                id=f"S{first_source_number + i}",
                title=r.title,
                url=r.source_url,
                section=r.section,
                season=r.season,
            )
            for i, r in enumerate(results)
        )
        payload = {
            "results": [
                {
                    "source": source.id,
                    "title": r.title,
                    "section": r.section,
                    "season": r.season,
                    "text": _cut(r.text),
                }
                for source, r in zip(sources, results, strict=True)
            ]
        }
        logger.info("Knowledge search: %d results, filters=%s", len(results), filters)
        return ToolOutcome(NAME, payload, ok=True, sources=sources)


def build_knowledge_tool(
    settings: Settings, session_factory: Callable[[], Session]
) -> KnowledgeTool:
    return KnowledgeTool(build_retriever(settings), session_factory)
