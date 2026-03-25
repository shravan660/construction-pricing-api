import uuid
from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from sqlalchemy.orm import Session

from app.database import get_db
from app.feedback.feedback_engine import store_feedback
from app.models.schemas import FeedbackRequest, FeedbackResponse

router = APIRouter()


@router.post("/feedback", response_model=FeedbackResponse, tags=["Feedback"])
def submit_feedback(req: FeedbackRequest, db: Session = Depends(get_db)):
    """
    Store contractor price feedback.

    Accepted feedback_type values: too_low | too_high | correct
    Accepted item_type values:     material | task

    Feedback is immediately persisted and will influence pricing in the
    next /price call for semantically similar items.
    """
    try:
        record = store_feedback(db, req)
        return FeedbackResponse(
            status="accepted",
            feedback_id=record.id,
            message=(
                f"Feedback recorded for '{req.item_label}'. "
                f"Future pricing for similar items will be adjusted accordingly."
            ),
        )
    except Exception as exc:
        logger.exception("Failed to store feedback for '%s'", req.item_label)
        raise HTTPException(status_code=500, detail="Internal server error while storing feedback.") from exc
