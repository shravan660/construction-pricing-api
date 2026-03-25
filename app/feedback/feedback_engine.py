"""
Feedback engine — stores contractor corrections and adjusts future pricing.

The basic idea: when a contractor says "that price was wrong, the real cost was X",
we store that and factor it into future quotes for similar items.

The adjustment uses exponential time decay so recent feedback matters more than
old feedback. λ=0.1 means feedback from a week ago has about half the weight of
today's feedback. This feels like a reasonable default but it's configurable.

For "similar items" matching I went with a keyword overlap approach rather than
running a second FAISS query. It's simpler and good enough for the common case
("Cumulus 200L" ↔ "chauffe-eau 200L"), but it'll miss pure synonyms that share
no words. The proper fix would be to embed the feedback labels and query FAISS —
just didn't have time to wire that up without complicating the code a lot.
"""

from __future__ import annotations

import math
from datetime import datetime

from loguru import logger
from sqlalchemy.orm import Session

from app.config import settings
from app.models.db_models import Feedback
from app.models.schemas import FeedbackRequest


def store_feedback(db: Session, req: FeedbackRequest) -> Feedback:
    """Persist a feedback record and return it."""
    # If the item was previously priced we could look up the predicted price from logs;
    # for simplicity we store None and use actual_price as the reference.
    record = Feedback(
        proposal_id=req.proposal_id,
        item_type=req.item_type,
        item_label=req.item_label,
        feedback_type=req.feedback_type,
        # We could look up the pricing_log for this proposal to get expected_price,
        # but that adds a query and the feedback still works without it
        expected_price=None,
        actual_price=req.actual_price,
        comment=req.comment,
        created_at=datetime.utcnow(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    logger.info(
        f"Feedback stored: [{req.feedback_type}] '{req.item_label}' "
        f"actual={req.actual_price}"
    )
    return record


def get_feedback_adjustment(
    db: Session,
    item_label: str,
    item_type: str,
    base_price: float,
) -> float:
    """
    Compute the weighted price adjustment (in EUR) for an item based
    on historical feedback.

    Returns a signed float: positive → price was too low → adjust up.
    """
    # Pull recent feedback for this item type — capping at 200 should be fine
    # for now. If we ever have thousands of feedback records per item we'd want
    # to pre-filter more aggressively, but that's a future problem.
    records = (
        db.query(Feedback)
        .filter(
            Feedback.item_type == item_type,
            Feedback.actual_price.isnot(None),
        )
        .order_by(Feedback.created_at.desc())
        .limit(200)
        .all()
    )

    # Filter to semantically similar items using simple keyword overlap
    label_words = set(item_label.lower().split())
    relevant = [
        r for r in records
        if _label_overlap(label_words, r.item_label)
    ]

    if not relevant:
        return 0.0

    decay_lambda = settings.FEEDBACK_DECAY_LAMBDA
    now = datetime.utcnow()
    total_weight = 0.0
    weighted_adj = 0.0

    for fb in relevant:
        days_old = max((now - fb.created_at).total_seconds() / 86_400, 0)
        weight = math.exp(-decay_lambda * days_old)

        # Adjustment direction:
        #   too_low  → actual > expected  → we need to increase predicted price
        #   too_high → actual < expected  → we need to decrease
        if fb.feedback_type == "too_low" and fb.actual_price:
            # Use the signed delta against the current base_price as reference
            adj = fb.actual_price - base_price
        elif fb.feedback_type == "too_high" and fb.actual_price:
            adj = fb.actual_price - base_price
        elif fb.feedback_type == "correct":
            adj = 0.0
        else:
            continue

        weighted_adj += weight * adj
        total_weight += weight

    if total_weight == 0:
        return 0.0

    result = round(weighted_adj / total_weight, 2)
    logger.debug(
        f"Feedback adjustment for '{item_label}': {result:+.2f}€ "
        f"(from {len(relevant)} record(s))"
    )
    return result


def _label_overlap(query_words: set[str], candidate_label: str) -> bool:
    """
    Returns True if the candidate label shares at least one meaningful word
    (>3 chars) with the query.  This provides coarse semantic grouping
    without requiring an extra embedding lookup.
    """
    candidate_words = set(candidate_label.lower().split())
    shared = query_words & candidate_words
    # Require at least one non-trivial word overlap
    return any(len(w) > 3 for w in shared)


def feedback_count(db: Session) -> int:
    return db.query(Feedback).count()
