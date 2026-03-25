"""
Regional price modifiers and contractor margin.

These are multiplicative factors on top of the base catalog price to account
for local market conditions. Paris is expensive, rural Normandie less so.

Based on INSEE regional construction cost indices — Occitanie = 1.0 baseline.
I hand-curated the city entries based on general knowledge; in a real system
you'd pull these from the INSEE API and refresh them periodically.

It's not a sophisticated model but it covers the most common French cities
and regions that would appear in proposals.
"""

from __future__ import annotations

# ─── Regional multipliers ──────────────────────────────────────────────────
# Keys normalised to lowercase without accents for fuzzy matching
_REGION_MODIFIERS: dict[str, float] = {
    # Regions
    "ile-de-france": 1.15,
    "île-de-france": 1.15,
    "occitanie": 1.00,
    "provence-alpes-cote-d-azur": 1.08,
    "provence-alpes-côte-d-azur": 1.08,
    "paca": 1.08,
    "auvergne-rhone-alpes": 1.05,
    "auvergne-rhône-alpes": 1.05,
    "nouvelle-aquitaine": 1.02,
    "bretagne": 0.98,
    "normandie": 0.97,
    "hauts-de-france": 0.99,
    "grand-est": 1.00,
    "pays-de-la-loire": 1.00,
    "centre-val-de-loire": 0.98,
    "bourgogne-franche-comte": 0.97,
    "bourgogne-franche-comté": 0.97,
    "corse": 1.10,
    # Cities
    "paris": 1.20,
    "lyon": 1.08,
    "marseille": 1.05,
    "montpellier": 1.00,
    "toulouse": 1.02,
    "bordeaux": 1.03,
    "nice": 1.12,
    "nantes": 1.02,
    "strasbourg": 1.03,
    "rennes": 1.00,
    "grenoble": 1.04,
    "lille": 1.01,
    "dijon": 0.98,
}

_DEFAULT_MODIFIER = 1.00


def get_regional_modifier(city: str | None, region: str | None) -> float:
    """
    Look up the regional modifier. City takes priority over region since
    it's more specific (Paris within Île-de-France has its own premium).
    Falls back to 1.00 (no adjustment) if we don't recognise the location.
    """
    for value in [city, region]:
        if not value:
            continue
        key = value.lower().strip().replace(" ", "-").replace("'", "-")
        modifier = _REGION_MODIFIERS.get(key)
        if modifier is not None:
            return modifier
    return _DEFAULT_MODIFIER


def apply_margin(cost: float, margin: float) -> float:
    """Apply a multiplicative contractor margin on top of the adjusted cost."""
    return round(cost * (1.0 + margin), 2)
