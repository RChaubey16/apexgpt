"""Saving feedback and the 90-day retention.

Retention runs in two places:
- every save deletes expired rows in the same transaction (an indexed DELETE,
  so no extra database wake-ups: Neon is awake for the insert anyway);
- `python -m app.feedback purge` does the same on its own, for a scheduled job
  (the weekly workflow, F7.3), so rows expire even when no feedback arrives.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from sqlalchemy import delete, func
from sqlalchemy.orm import Session

from app.db.models.feedback import MAX_EXCERPT_CHARS, Feedback

logger = logging.getLogger(__name__)

RETENTION_DAYS = 90


@dataclass(frozen=True)
class NewFeedback:
    rating: Literal["up", "down"]
    question: str
    answer: str  # the full answer; only an excerpt is stored
    provider: str | None = None
    model: str | None = None


def excerpt(answer: str, limit: int = MAX_EXCERPT_CHARS) -> str:
    """The start of an answer, at most `limit` characters, cut at a word."""
    text = answer.strip()
    if len(text) <= limit:
        return text
    head = text[: limit - 1]
    cut = head.rsplit(None, 1)[0] if " " in head else head
    return cut.rstrip() + "…"


def purge_expired(session: Session, *, days: int = RETENTION_DAYS) -> int:
    """Delete feedback older than `days`; returns how many rows. Doesn't commit."""
    result = session.execute(
        delete(Feedback).where(Feedback.created_at < func.now() - timedelta(days=days))
    )
    return result.rowcount or 0


def save_feedback(session: Session, feedback: NewFeedback) -> int:
    """Store one rating and purge expired rows, in one transaction; returns the
    new row's id. Database errors propagate (the caller decides the message)."""
    row = Feedback(
        rating=feedback.rating,
        question=feedback.question,
        answer_excerpt=excerpt(feedback.answer),
        provider=feedback.provider,
        model=feedback.model,
    )
    session.add(row)
    purged = purge_expired(session)
    session.commit()
    if purged:
        logger.info(
            "Feedback purged: %d rows older than %d days", purged, RETENTION_DAYS
        )
    return row.id
