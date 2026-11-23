"""Answer feedback (F4.3): a thumbs up or down on one answer.

Kept for RETENTION_DAYS (app/feedback). No IP address or other user identifier
is stored: only what was asked, the start of the answer, the rating and which
model answered (to compare providers in F6).
"""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Identity, Index, Text
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

RATINGS = ("up", "down")
MAX_QUESTION_CHARS = 500
MAX_EXCERPT_CHARS = 500
MAX_PROVIDER_CHARS = 40
MAX_MODEL_CHARS = 200


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint(
            "rating IN (" + ", ".join(f"'{r}'" for r in RATINGS) + ")",
            name="rating_valid",
        ),
        CheckConstraint(
            f"length(question) BETWEEN 1 AND {MAX_QUESTION_CHARS}",
            name="question_length",
        ),
        CheckConstraint(
            f"length(answer_excerpt) BETWEEN 1 AND {MAX_EXCERPT_CHARS}",
            name="answer_excerpt_length",
        ),
        CheckConstraint(
            f"length(provider) <= {MAX_PROVIDER_CHARS}", name="provider_length"
        ),
        CheckConstraint(f"length(model) <= {MAX_MODEL_CHARS}", name="model_length"),
        # The retention purge deletes by age.
        Index("ix_feedback_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa_func.now()
    )
    rating: Mapped[str] = mapped_column(Text)
    question: Mapped[str] = mapped_column(Text)
    answer_excerpt: Mapped[str] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
