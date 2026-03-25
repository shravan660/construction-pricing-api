"""
Material pricer — semantic search → price matching.

This is the core of the pricing pipeline for materials. The idea is simple:
take the material label, embed it, find the closest product in the FAISS index,
use that product's price as the base, then layer on regional/feedback/margin.

The main limitation is that match quality depends heavily on how much seed/scraped
data we have. A "200L water heater" will match well; something obscure like a
specific tile adhesive brand might get a low confidence score and a mediocre match.
Could improve this with more catalog data or a reranking step, but good enough for now.
"""

from __future__ import annotations

from loguru import logger

from app.models.schemas import AlternativeProduct, MaterialInput, PricedMaterial
from app.pricing.modifiers import apply_margin, get_regional_modifier
from app.search.vector_store import search


def price_material(
    material: MaterialInput,
    regional_modifier: float,
    feedback_adjustment: float,
    contractor_margin: float,
    top_k: int = 5,
) -> PricedMaterial:
    """
    Price a single material item using semantic search.

    Args:
        material:            Input material (label, unit, quantity).
        regional_modifier:   Multiplier for local market (e.g. 1.15 for Paris).
        feedback_adjustment: Euro-value adjustment from the feedback loop.
        contractor_margin:   Fraction to add as margin (e.g. 0.15 → +15%).
        top_k:               Number of candidates retrieved from the index.
    """
    query = f"{material.label} {material.unit or ''}".strip()
    hits = search(query, top_k=top_k)

    if not hits:
        # Shouldn't happen in practice if the index is built, but just in case
        logger.warning(f"No search results for material: {material.label}")
        return _fallback_material(material, contractor_margin)

    best = hits[0]
    unit_price: float = best["price"]
    confidence: float = best["confidence_score"]

    # Regional modifier goes on the unit price, not the total — intentional
    adjusted_unit = unit_price * regional_modifier

    base_cost = round(adjusted_unit * material.quantity, 2)
    # feedback_adjustment is already a signed EUR value from the feedback engine
    adjusted_cost = round(base_cost + feedback_adjustment, 2)
    with_margin = apply_margin(adjusted_cost, contractor_margin)

    # Grab alternatives from the remaining hits — useful for the contractor to see options
    # Capping at 3 feels right; more than that is noise
    alternatives = [
        AlternativeProduct(
            product=h["name"],
            price=h["price"],
            confidence=h["confidence_score"],
        )
        for h in hits[1:4]
    ]

    return PricedMaterial(
        label=material.label,
        matched_product=best["name"],
        confidence_score=round(confidence, 4),
        unit_price=round(adjusted_unit, 2),
        quantity=material.quantity,
        base_cost=base_cost,
        regional_modifier=regional_modifier,
        feedback_adjustment=round(feedback_adjustment, 2),
        adjusted_cost=adjusted_cost,
        with_margin=with_margin,
        source=best.get("source", "bricodepot.fr"),
        alternatives=alternatives,
    )


def _fallback_material(material: MaterialInput, contractor_margin: float) -> PricedMaterial:
    """Return a zeroed-out entry when no catalog match is found."""
    return PricedMaterial(
        label=material.label,
        matched_product=None,
        confidence_score=0.0,
        unit_price=0.0,
        quantity=material.quantity,
        base_cost=0.0,
        regional_modifier=1.0,
        feedback_adjustment=0.0,
        adjusted_cost=0.0,
        with_margin=0.0,
        source="no_match",
        alternatives=[],
    )
