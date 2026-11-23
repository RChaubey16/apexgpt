"""`POST /api/feedback`: a thumbs up or down on an answer (F4.3).

Request (unknown fields are rejected):

    {"rating": "up" | "down",
     "question": "...",          # 1-500 characters, the question answered
     "answer": "...",            # 1-8,000 characters; only the first 500 are kept
     "provider": "groq",         # optional, from the chat `done` event
     "model": "openai/gpt-oss-120b"}

Response: 201 `{"id": <int>}`. 422 for a bad body; 429 with Retry-After over
the per-IP limit (RATE_LIMIT_FEEDBACK, F4.4); 503 when the database can't
store it (the message is safe to show). Kept for 90 days.
"""

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.answer.followups import MAX_HISTORY_CHARS
from app.core.rate_limit import rate_limit
from app.db.models.feedback import (
    MAX_MODEL_CHARS,
    MAX_PROVIDER_CHARS,
    MAX_QUESTION_CHARS,
)
from app.db.session import get_session
from app.feedback import NewFeedback, save_feedback

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["feedback"])

UNAVAILABLE = "Feedback could not be saved right now; please try again later"


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    rating: Literal["up", "down"]
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    # As long as an answer the chat history accepts.
    answer: str = Field(min_length=1, max_length=MAX_HISTORY_CHARS)
    provider: str | None = Field(
        default=None, min_length=1, max_length=MAX_PROVIDER_CHARS
    )
    model: str | None = Field(default=None, min_length=1, max_length=MAX_MODEL_CHARS)


class FeedbackResponse(BaseModel):
    id: int


class ErrorResponse(BaseModel):
    detail: str


@router.post(
    "/feedback",
    status_code=status.HTTP_201_CREATED,
    response_model=FeedbackResponse,
    responses={429: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    dependencies=[Depends(rate_limit("feedback"))],
)
def create_feedback(
    body: FeedbackRequest, session: Annotated[Session, Depends(get_session)]
) -> FeedbackResponse | JSONResponse:
    try:
        feedback_id = save_feedback(
            session,
            NewFeedback(body.rating, body.question, body.answer, body.provider,
                        body.model),
        )  # fmt: skip
    except SQLAlchemyError as exc:
        # The session is closed (and rolled back) by get_session.
        # The error class only: driver messages can include host details.
        logger.warning(
            "Feedback not saved: %s",
            type(exc).__name__,
            extra={"event": "feedback", "outcome": "error",
                   "error_type": type(exc).__name__},
        )  # fmt: skip
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": UNAVAILABLE},
        )
    logger.info(
        "Feedback saved",
        extra={"event": "feedback", "outcome": "ok", "id": feedback_id,
               "rating": body.rating, "provider": body.provider},
    )  # fmt: skip
    return FeedbackResponse(id=feedback_id)
