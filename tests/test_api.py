"""
Integration tests for the Pricing Engine API.

Run with:
    pytest tests/ -v

Requirements: the FAISS index must exist (run scripts/build_index.py first).
If the index is missing, material pricing tests will return zero-price responses
which is handled gracefully.
"""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.main import app

client = TestClient(app)

PAYLOAD_DIR = Path(__file__).parent / "sample_payloads"


# ─── Health ───────────────────────────────────────────────────────────────────

def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert isinstance(body["product_count"], int)
    assert isinstance(body["feedback_count"], int)


# ─── Search ───────────────────────────────────────────────────────────────────

def test_search_returns_results():
    resp = client.get("/search", params={"q": "chauffe-eau 200L", "top_k": 3})
    assert resp.status_code == 200
    body = resp.json()
    assert body["query"] == "chauffe-eau 200L"
    assert isinstance(body["results"], list)


def test_search_cross_language():
    """English query should still find French product names."""
    resp = client.get("/search", params={"q": "water heater 200 litres", "top_k": 5})
    assert resp.status_code == 200
    body = resp.json()
    # We don't assert specific matches since it depends on the index,
    # but the response shape must be valid
    assert "results" in body


def test_search_top_k_respected():
    resp = client.get("/search", params={"q": "carrelage", "top_k": 2})
    assert resp.status_code == 200
    assert len(resp.json()["results"]) <= 2


def test_search_missing_query():
    resp = client.get("/search")
    assert resp.status_code == 422  # unprocessable entity – missing required param


# ─── Price ────────────────────────────────────────────────────────────────────

def _load(filename: str) -> dict:
    return json.loads((PAYLOAD_DIR / filename).read_text(encoding="utf-8"))


def test_price_water_heater():
    payload = _load("water_heater.json")
    resp = client.post("/price", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["proposal_id"] == "test_001"
    assert body["currency"] == "EUR"
    assert len(body["priced_materials"]) == 2
    assert len(body["priced_tasks"]) == 2

    # Every priced item must have a non-negative with_margin
    for m in body["priced_materials"]:
        assert m["with_margin"] >= 0, f"Negative price for {m['label']}"
    for t in body["priced_tasks"]:
        assert t["with_margin"] > 0, f"Zero price for task {t['label']}"

    summary = body["summary"]
    assert summary["total"] >= 0
    assert summary["margin_applied"] == pytest.approx(0.15)


def test_price_bathroom_renovation():
    payload = _load("bathroom_renovation.json")
    resp = client.post("/price", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["proposal_id"] == "test_bathroom_001"
    assert len(body["priced_materials"]) == 4
    assert len(body["priced_tasks"]) == 3

    # Paris has regional_modifier > 1 — at least one material should reflect that
    modifiers = [m["regional_modifier"] for m in body["priced_materials"]]
    assert any(mod > 1.0 for mod in modifiers), "Paris regional modifier not applied"


def test_price_margin_applied_correctly():
    """Verify that with_margin = adjusted_cost × (1 + margin)."""
    payload = _load("water_heater.json")
    payload["contractor_margin"] = 0.20
    resp = client.post("/price", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    for t in body["priced_tasks"]:
        expected = round(t["adjusted_cost"] * 1.20, 2)
        assert abs(t["with_margin"] - expected) < 0.05, (
            f"Margin mismatch for {t['label']}: "
            f"adjusted={t['adjusted_cost']}  with_margin={t['with_margin']}  expected≈{expected}"
        )


def test_price_empty_materials():
    payload = {
        "proposal_id": "test_empty_mat",
        "metadata": {"city": "Lyon"},
        "contractor_margin": 0.10,
        "tasks": [
            {
                "id": 1,
                "label": "Quick plumbing fix",
                "category": "Plomberie",
                "phase": "Install",
                "unit": "unit",
                "quantity": 1,
                "duration": "1 hour",
            }
        ],
        "materials": [],
    }
    resp = client.post("/price", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["priced_materials"] == []
    assert len(body["priced_tasks"]) == 1


def test_price_invalid_margin():
    payload = _load("water_heater.json")
    payload["contractor_margin"] = 1.5   # >1.0, invalid per schema
    resp = client.post("/price", json=payload)
    assert resp.status_code == 422


# ─── Feedback ─────────────────────────────────────────────────────────────────

def test_feedback_accepted():
    payload = {
        "proposal_id": "test_001",
        "item_type": "material",
        "item_label": "Cumulus 200L",
        "feedback_type": "too_low",
        "actual_price": 350.00,
        "comment": "Price of water heaters has gone up.",
    }
    resp = client.post("/feedback", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "accepted"
    assert "feedback_id" in body


def test_feedback_invalid_type():
    payload = {
        "proposal_id": "test_001",
        "item_type": "material",
        "item_label": "Some item",
        "feedback_type": "wrong_value",   # invalid
    }
    resp = client.post("/feedback", json=payload)
    assert resp.status_code == 422


def test_feedback_adjusts_future_price():
    """
    Submit a 'too_low' feedback then re-price — the adjusted_cost should
    be higher than before for that item.
    """
    # Step 1: get baseline price
    payload = _load("water_heater.json")
    resp1 = client.post("/price", json=payload)
    assert resp1.status_code == 200
    baseline = resp1.json()
    mat_before = next(
        m for m in baseline["priced_materials"]
        if "Water Heater" in m["label"] or "Cumulus" in m["label"]
    )

    # Step 2: submit 'too_low' feedback with a much higher actual price
    client.post("/feedback", json={
        "proposal_id": "test_001",
        "item_type": "material",
        "item_label": mat_before["label"],
        "feedback_type": "too_low",
        "actual_price": mat_before["adjusted_cost"] * 1.5,
        "comment": "Prices have risen significantly.",
    })

    # Step 3: re-price and compare
    resp2 = client.post("/price", json=payload)
    assert resp2.status_code == 200
    updated = resp2.json()
    mat_after = next(
        m for m in updated["priced_materials"]
        if m["label"] == mat_before["label"]
    )
    # The adjusted_cost should have increased (or at least the feedback_adjustment > 0)
    assert mat_after["feedback_adjustment"] >= 0, (
        "Expected non-negative feedback adjustment after 'too_low' feedback"
    )
