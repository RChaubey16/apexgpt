"""Answer feedback (F4.3): store a thumbs up/down and keep it for 90 days.

    feedback_id = save_feedback(session, NewFeedback("up", question, answer))
    purge_expired(session)  # also run by every save, and by the CLI

Try it: `uv run python -m app.feedback purge` (deletes rows older than 90 days).
"""

from app.feedback.store import (
    RETENTION_DAYS,
    NewFeedback,
    excerpt,
    purge_expired,
    save_feedback,
)

__all__ = ["RETENTION_DAYS", "NewFeedback", "excerpt", "purge_expired", "save_feedback"]
