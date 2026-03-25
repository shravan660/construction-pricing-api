"""
POST /price — core pricing endpoint.

Pipeline:
  1. Resolve regional modifier (city / region)
  2. For each material:  semantic search → best match price
                          + feedback adjustment + margin
  3. For each task:      labor-rate formula (rate × hours × phase factor)
                          + feedback adjustment + margin
  4. Log every priced item to the pricing_logs table
  5. Return full ProposalResponse
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.feedback.feedback_engine import get_feedback_adjustment
from app.models.db_models import PricingLog
from app.models.schemas import (
    PricedMaterial,
    PricedTask,
    PricingSummary,
    ProposalRequest,
    ProposalResponse,
)
from app.pricing.material_pricer import price_material
from app.pricing.modifiers import get_regional_modifier
from app.pricing.task_pricer import price_task

router = APIRouter()


@router.post("/price", response_model=ProposalResponse, tags=["Pricing"])
def price_proposal(req: ProposalRequest, db: Session = Depends(get_db)):
    """
    Accept a construction proposal and return fully priced materials and tasks.

    - Materials are priced via semantic search against the scraped BricoDepôt catalogue.
    - Tasks are priced via a transparent labor-rate formula.
    - Both are adjusted for regional market conditions, contractor feedback history,
      and the requested contractor margin.
    """
    meta = req.metadata or {}

    # ── 1. Regional modifier ────────────────────────────────────────────────
    city = getattr(meta, "city", None)
    region = getattr(meta, "region", None)
    regional_mod = get_regional_modifier(city, region)

    # ── 2. Price materials ─────────────────────────────────────────────────
    priced_materials: list[PricedMaterial] = []
    for mat in req.materials:
        # Estimate base price first to anchor feedback calculation
        search_result = _quick_search_price(mat.label)
        base_estimate = search_result * mat.quantity * regional_mod if search_result else 0.0

        fb_adj = get_feedback_adjustment(
            db,
            item_label=mat.label,
            item_type="material",
            base_price=base_estimate,
        )

        pm = price_material(
            material=mat,
            regional_modifier=regional_mod,
            feedback_adjustment=fb_adj,
            contractor_margin=req.contractor_margin,
        )
        priced_materials.append(pm)

        # Log it
        _log(
            db,
            proposal_id=req.proposal_id,
            item_label=mat.label,
            item_type="material",
            base_price=pm.base_cost,
            regional_modifier=regional_mod,
            feedback_adjustment=fb_adj,
            adjusted_cost=pm.adjusted_cost,
            margin_applied=req.contractor_margin,
            final_price=pm.with_margin,
            confidence_score=pm.confidence_score,
            pricing_method="semantic_search",
            pricing_details=f"Matched: {pm.matched_product} (conf={pm.confidence_score:.2f})",
        )

    # ── 3. Price tasks ──────────────────────────────────────────────────────
    priced_tasks: list[PricedTask] = []
    for task in req.tasks:
        fb_adj = get_feedback_adjustment(
            db,
            item_label=task.label,
            item_type="task",
            base_price=0.0,  # we don't have a catalog price; use 0 as anchor
        )

        pt = price_task(
            task=task,
            regional_modifier=regional_mod,
            feedback_adjustment=fb_adj,
            contractor_margin=req.contractor_margin,
        )
        priced_tasks.append(pt)

        _log(
            db,
            proposal_id=req.proposal_id,
            item_label=task.label,
            item_type="task",
            base_price=pt.base_cost,
            regional_modifier=regional_mod,
            feedback_adjustment=fb_adj,
            adjusted_cost=pt.adjusted_cost,
            margin_applied=req.contractor_margin,
            final_price=pt.with_margin,
            confidence_score=None,
            pricing_method=pt.pricing_method,
            pricing_details=pt.pricing_details,
        )

    # ── 4. Compute summary ──────────────────────────────────────────────────
    mat_subtotal = round(sum(m.with_margin for m in priced_materials), 2)
    task_subtotal = round(sum(t.with_margin for t in priced_tasks), 2)
    total = round(mat_subtotal + task_subtotal, 2)

    confidences = [m.confidence_score for m in priced_materials if m.confidence_score > 0]
    avg_conf = round(sum(confidences) / len(confidences), 3) if confidences else 0.0

    summary = PricingSummary(
        materials_subtotal=mat_subtotal,
        tasks_subtotal=task_subtotal,
        total=total,
        avg_material_confidence=avg_conf,
        pricing_metadata={
            "scraped_data_date": _get_data_date(),
            "model_version": settings.VERSION,
            "margin_applied": req.contractor_margin,
            "regional_modifier": regional_mod,
            "city": city,
            "region": region,
        },
    )

    return ProposalResponse(
        proposal_id=req.proposal_id,
        currency="EUR",
        priced_materials=priced_materials,
        priced_tasks=priced_tasks,
        summary=summary,
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _quick_search_price(label: str) -> float | None:
    """Single-result search used to anchor the feedback adjustment calculation."""
    try:
        from app.search.vector_store import search as vector_search
        hits = vector_search(label, top_k=1)
        return hits[0]["price"] if hits else None
    except Exception:
        return None


def _log(
    db: Session,
    *,
    proposal_id: str,
    item_label: str,
    item_type: str,
    base_price: float,
    regional_modifier: float,
    feedback_adjustment: float,
    adjusted_cost: float,
    margin_applied: float,
    final_price: float,
    confidence_score: float | None,
    pricing_method: str,
    pricing_details: str,
) -> None:
    record = PricingLog(
        proposal_id=proposal_id,
        item_label=item_label,
        item_type=item_type,
        base_price=base_price,
        regional_modifier=regional_modifier,
        feedback_adjustment=feedback_adjustment,
        adjusted_cost=adjusted_cost,
        margin_applied=margin_applied,
        final_price=final_price,
        confidence_score=confidence_score,
        pricing_method=pricing_method,
        pricing_details=pricing_details,
        created_at=datetime.utcnow(),
    )
    db.add(record)
    db.commit()


def _get_data_date() -> str:
    """Return the date of the most recent processed data file."""
    import os
    from pathlib import Path

    processed = Path(settings.PROCESSED_DATA_PATH)
    if not processed.exists():
        return "N/A"
    files = sorted(processed.glob("products_*.json"), reverse=True)
    if files:
        ts_str = files[0].stem.replace("products_", "")
        try:
            dt = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
    return datetime.utcnow().strftime("%Y-%m-%d")
