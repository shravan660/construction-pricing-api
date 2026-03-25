"""
Task (labor) pricer.

Tasks are the tricky part — there's no product catalog for labor, so you can't
do semantic search. I considered a few approaches:
  - Call an LLM per task: too slow, adds external dependency, hard to test
  - Scrape Batiprix rate sheets: would be ideal but they're behind a paywall
  - Formula based on published estimates: transparent, fast, good enough

Went with the formula. The rates are seeded from Batiprix / OPPBTP 2024 indices.
Not perfect but at least explainable — the API response shows exactly where the
number came from, which is what matters for a contractor reviewing a quote.

Formula: base = hourly_rate × hours × phase_complexity × regional_modifier
"""

from __future__ import annotations

import re

from loguru import logger

from app.models.schemas import PricedTask, TaskInput
from app.pricing.modifiers import apply_margin


# ─── Labor rates (EUR / hour) ─────────────────────────────────────────────────
# Sourced from Batiprix / OPPBTP 2024 published indices.
# Both French and English keys because the upstream pipeline can send either.
# TODO: would be nice to pull these from a config file or DB so they're updatable
# without a deploy — for now hardcoding is fine
_LABOR_RATES: dict[str, float] = {
    "plomberie": 45.0,
    "plumbing": 45.0,
    "electricite": 50.0,
    "électricité": 50.0,
    "electrical": 50.0,
    "electricity": 50.0,
    "carrelage": 35.0,
    "tiling": 35.0,
    "menuiserie": 40.0,
    "carpentry": 40.0,
    "joinery": 40.0,
    "maçonnerie": 38.0,
    "masonry": 38.0,
    "peinture": 28.0,
    "painting": 28.0,
    "isolation": 32.0,
    "insulation": 32.0,
    "chauffage": 48.0,
    "heating": 48.0,
    "climatisation": 50.0,
    "air conditioning": 50.0,
    "toiture": 55.0,
    "roofing": 55.0,
    "default": 35.0,
}

# ─── Phase complexity multipliers ─────────────────────────────────────────────
# Prep work is simpler (less skill required), finishing is more precise = costs more.
# These are rough industry rules of thumb, not from a published source.
_PHASE_COMPLEXITY: dict[str, float] = {
    "prep": 0.80,
    "preparation": 0.80,
    "demo": 0.75,
    "demolition": 0.75,
    "dépose": 0.75,
    "install": 1.00,
    "installation": 1.00,
    "pose": 1.00,
    "finish": 1.10,
    "finishing": 1.10,
    "finition": 1.10,
    "verification": 0.90,
    "commissioning": 0.90,
    "mise en service": 0.90,
    "default": 1.00,
}


def price_task(
    task: TaskInput,
    regional_modifier: float,
    feedback_adjustment: float,
    contractor_margin: float,
) -> PricedTask:
    """
    Price a single labor task.

    Returns a PricedTask with full pricing breakdown and audit trail.
    """
    hourly_rate = _get_labor_rate(task.category)
    hours = _parse_duration_hours(task.duration)
    phase_factor = _get_phase_factor(task.phase)

    estimated_unit_price = round(hourly_rate * hours * phase_factor * regional_modifier, 2)
    base_cost = round(estimated_unit_price * task.quantity, 2)
    adjusted_cost = round(base_cost + feedback_adjustment, 2)
    with_margin = apply_margin(adjusted_cost, contractor_margin)

    details = (
        f"Based on {task.category or 'general'} labor rate ({hourly_rate:.0f}€/h) "
        f"× {hours:.1f}h"
    )
    if phase_factor != 1.0:
        details += f" × phase complexity {phase_factor:.2f} ({task.phase or 'default'})"
    if regional_modifier != 1.0:
        details += f" × regional factor {regional_modifier:.2f}"

    return PricedTask(
        id=task.id,
        label=task.label,
        category=task.category,
        estimated_unit_price=estimated_unit_price,
        quantity=task.quantity,
        base_cost=base_cost,
        feedback_adjustment=round(feedback_adjustment, 2),
        adjusted_cost=adjusted_cost,
        with_margin=with_margin,
        pricing_method="labor_rate_estimation",
        pricing_details=details,
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_labor_rate(category: str | None) -> float:
    if not category:
        return _LABOR_RATES["default"]
    key = category.lower().strip()
    return _LABOR_RATES.get(key, _LABOR_RATES["default"])


def _parse_duration_hours(duration: str | None) -> float:
    """
    Parse natural-language duration strings into decimal hours.

    Supports French and English:
      '2 hours', '3h', '1 jour', '2 jours', '30 minutes',
      '1.5 heures', '2 days'
    """
    if not duration:
        # The upstream AI pipeline should always provide this, but just in case
        return 1.0

    text = duration.lower().strip()

    # Demi-journée / half-day
    if "demi" in text or "half" in text:
        return 4.0

    # Days (French & English)
    day_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:jour|jours|day|days|j\b)", text)
    if day_match:
        return float(day_match.group(1).replace(",", ".")) * 8.0

    # Hours
    hour_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:heure|heures|hour|hours|h\b)", text)
    if hour_match:
        return float(hour_match.group(1).replace(",", "."))

    # Minutes
    min_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:minute|minutes|min)", text)
    if min_match:
        return float(min_match.group(1).replace(",", ".")) / 60.0

    # Bare number — assume hours
    bare = re.search(r"(\d+(?:[.,]\d+)?)", text)
    if bare:
        return float(bare.group(1).replace(",", "."))

    logger.warning(f"Could not parse duration '{duration}', defaulting to 1h")
    return 1.0


def _get_phase_factor(phase: str | None) -> float:
    if not phase:
        return _PHASE_COMPLEXITY["default"]
    key = phase.lower().strip()
    return _PHASE_COMPLEXITY.get(key, _PHASE_COMPLEXITY["default"])
