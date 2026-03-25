# Construction Pricing API

## Overview

A REST API that takes a construction proposal (list of materials and tasks) and returns realistic, market-informed price estimates. It matches materials to real French catalog data using semantic search, prices labor tasks using published market rates, and applies regional cost adjustments with a time-decay feedback correction loop.

---

## Features

- Semantic search to match free-text material descriptions to BricoDepôt catalog products
- Multilingual support — handles French and English queries in the same request
- Price estimation for both materials (catalog-matched) and labor tasks (formula-based)
- Regional price modifiers for 30+ French cities and regions
- Contractor feedback loop with time-decay weighting — recent feedback weighs more
- Persistent pricing logs in SQLite for audit and analytics
- Interactive API docs at `/docs` out of the box

---

## Tech Stack

| Component | Choice |
|-----------|--------|
| Language | Python 3.11+ |
| Framework | FastAPI |
| Embedding Model | `paraphrase-multilingual-MiniLM-L12-v2` (sentence-transformers) |
| Vector Search | FAISS `IndexFlatIP` |
| Database | SQLite via SQLAlchemy (swap to Postgres with one env var) |
| Scraper | Playwright (headless Chromium) |
| Container | Docker + docker-compose |

---

## Architecture

```
Scraper (Playwright)
    ¦
    ?
Embedder (MiniLM-L12, 384-dim)
    ¦
    ?
FAISS Index (products.index)
    ¦
    ?
FastAPI REST API
    +-- POST /price   ? Material Pricer (semantic search ? unit price ? modifiers)
    ¦                 ? Task Pricer    (hourly rate × hours × phase factor)
    ¦                 ? Modifiers      (regional multiplier + contractor margin)
    ¦
    +-- POST /feedback ? Feedback Engine (time-decay weighted adjustment)
    +-- GET  /search   ? Raw vector search
    +-- GET  /health   ? Status + index info
    ¦
    ?
SQLite  (products | feedback | pricing_logs)
```

**Request flow for `POST /price`:**
1. Each material label is embedded ? FAISS finds closest catalog match
2. Unit price × quantity ? apply regional modifier ? apply feedback delta ? apply margin
3. Each task ? `hourly_rate × hours × phase_complexity × regional modifier × margin`
4. All line items aggregated into a single total

---

## API Endpoints

### `POST /price`
Price a full construction proposal (materials + tasks).

**Request:**
```json
{
  "project_type": "bathroom renovation",
  "location": "Paris",
  "contractor_margin": 0.15,
  "materials": [
    { "label": "Electric water heater 200L", "quantity": 1, "unit": "unit" }
  ],
  "tasks": [
    { "label": "Plumbing installation", "category": "Plomberie", "duration": "3 heures", "phase": "installation" }
  ]
}
```

**Response (per material):**

| Field | Meaning |
|-------|---------|
| `matched_product` | Catalog product the label was matched to |
| `confidence_score` | Cosine similarity (0–1) |
| `base_cost` | `unit_price × quantity × regional_modifier` |
| `feedback_adjustment` | EUR delta from historical contractor feedback |
| `with_margin` | Final cost including contractor margin |
| `alternatives` | Up to 3 other candidate matches |

---

### `POST /feedback`
Submit a price correction for a previously priced item.

```json
{
  "proposal_id": "test_001",
  "item_type": "material",
  "item_label": "Cumulus 200L",
  "feedback_type": "too_low",
  "actual_price": 350.00,
  "comment": "Prices have gone up."
}
```

`feedback_type` accepts: `too_low`, `too_high`, `correct`

---

### `GET /search?q={query}&top_k={k}`
Raw semantic search against the product catalog.

```bash
curl "http://localhost:8000/search?q=chauffe-eau+200L&top_k=3"
```

---

### `GET /health`
Returns API status, FAISS index state, and product count.

---

## How to Run

### Option 1 — One command (recommended)

**Windows (PowerShell):**
```powershell
.\start.ps1
```

**macOS / Linux:**
```bash
chmod +x start.sh && ./start.sh
```

The script handles: venv creation ? dependency install ? FAISS index build ? server start.
API will be live at **http://localhost:8000** | Docs at **http://localhost:8000/docs**

---

### Option 2 — Manual steps

```bash
# 1. Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS/Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Build the FAISS index (uses built-in seed data — no scraping needed)
python scripts/build_index.py --use-seed

# 4. Start the API
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

### Option 3 — Docker

```bash
docker compose up --build
```

---

### Run Tests

```bash
python scripts/build_index.py --use-seed   # index must exist first
pytest tests/ -v
```

---

## Future Improvements

- **Better feedback matching** — use FAISS to find semantically similar feedback entries instead of keyword overlap (would fix the "cumulus" vs "chauffe-eau" blind spot)
- **Live task rate data** — parse Batiprix PDF or integrate OPPBTP API instead of hardcoded estimates
- **Incremental FAISS updates** — current setup rebuilds the full index on each scrape run; should support upsert
- **Authentication** — API key middleware or OAuth2 (currently all endpoints are open)
- **Confidence threshold flag** — surface a clear `low_confidence: true` flag when match score < 0.5
- **Postgres migration** — SQLAlchemy ORM is already set up for it; just an env var change away
- **Test coverage for `/feedback`** — current test suite covers pricing and search but not the feedback endpoint
