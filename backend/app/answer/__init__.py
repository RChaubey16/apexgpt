"""Grounded answers from the LLM and the tools (Phase 3).

    from app.answer import build_orchestrator
    answer = build_orchestrator(settings).answer("Who has the most wins at Monza?")

Try it: `uv run python -m app.answer "question"`.
"""

from sqlalchemy.orm import Session, sessionmaker

from app.answer.cache import AnswerCache
from app.answer.orchestrator import (
    Answer,
    AnswerUnavailableError,
    Orchestrator,
    ToolCallRecord,
)
from app.core.config import Settings
from app.db.session import create_db_engine
from app.llm import build_llm_client
from app.retrieval.entities import EntityResolver, load_entity_index
from app.tools.knowledge import build_knowledge_tool
from app.tools.stats import StatsTool


def build_orchestrator(
    settings: Settings, session_factory: "sessionmaker[Session] | None" = None
) -> Orchestrator:
    """The LLM client, both tools and entity resolution, from settings."""
    if session_factory is None:
        session_factory = sessionmaker(bind=create_db_engine(settings))

    def load_index():
        with session_factory() as session:
            return load_entity_index(session)

    cache = (
        AnswerCache(settings.answer_cache_size, settings.answer_cache_ttl_seconds)
        if settings.answer_cache_size
        else None
    )
    return Orchestrator(
        build_llm_client(settings),
        [
            StatsTool.from_settings(settings),
            build_knowledge_tool(settings, session_factory),
        ],
        EntityResolver(load_index),
        cache=cache,
    )


__all__ = [
    "Answer",
    "AnswerUnavailableError",
    "Orchestrator",
    "ToolCallRecord",
    "build_orchestrator",
]
