# Construction Pricing API

## Problem Statement

Construction companies receive quotes in natural language  contractors write things like "electric water heater 200L" or "chauffe-eau 200L". Traditional keyword search fails to match these against product catalogs accurately, causing wrong pricing or manual lookup overhead.

This API solves that by using semantic search to find the closest matching product regardless of exact wording or language.

---

## Overview

A FastAPI-based backend that estimates construction material and labor pricing using **semantic search**.
Matches free-text material descriptions to real French catalog products, handles French + English queries, applies regional cost modifiers, and learns from contractor feedback via a time-decay correction loop.

---

## Key Features

* Semantic material search using FAISS + sentence-transformers
* Real-time pricing estimation for materials and labor tasks
* Multilingual matching  French and English queries work out of the box
* Regional price modifiers for 30+ French cities and regions
* Contractor feedback loop with time-decay weighting
* Persistent pricing logs in SQLite (swappable to Postgres with one env var)
* Auto-generated interactive API docs at `/docs`

---

## Why Semantic Search?

Traditional systems rely on keyword matching, which fails when contractors describe materials in natural language.

This system:

* Understands intent  `"electric water heater 200L"` matches `"chauffe-eau lectrique 200L vertical"`
* Works across languages  proposal in English, catalog in French, no preprocessing needed
* Ranks candidates by cosine similarity so the best match is always at the top
* Returns up to 3 alternative matches with confidence scores for transparency

---

## Architecture

```
User Query  Embedder (MiniLM-L12)  FAISS Index  Best Match  Pricing Engine  API Response
                                                                       |
                                                           Regional Modifier x Feedback Delta x Margin
```

**Full request flow for `POST /price`:**
1. Each material label is embedded  FAISS finds closest catalog match
2. `unit_price x quantity`  regional modifier  feedback delta  contractor margin
3. Each task  `hourly_rate x hours x phase_complexity x regional modifier x margin`
4. All line items aggregated into a single total

---

## API Example

### `POST /price`

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

**Response:**
```json
{
  "total": 304.05,
  "materials": [
    {
      "label": "Electric water heater 200L",
      "matched_product": "Chauffe-eau lectrique 200L",
      "confidence_score": 0.87,
      "with_margin": 241.55
    }
  ],
  "tasks": [
    {
      "label": "Plumbing installation",
      "estimated_unit_price": 62.50,
      "pricing_method": "labor_rate_estimation"
    }
  ]
}
```

### `POST /feedback`
Submit a price correction. Influences future `/price` calls for similar items.

### `GET /search?q={query}&top_k={k}`
Raw semantic search against the product catalog.

### `GET /health`
Returns API status, FAISS index state, and product count.

---

## Tech Stack

| Component | Choice |
|-----------|--------|
| Language | Python 3.11+ |
| Framework | FastAPI |
| Embedding Model | `paraphrase-multilingual-MiniLM-L12-v2` |
| Vector Search | FAISS `IndexFlatIP` |
| Database | SQLite via SQLAlchemy |
| Scraper | Playwright (headless Chromium) |
| Container | Docker + docker-compose |

---

## How to Run

**One command (recommended):**

```powershell
# Windows
.\start.ps1
```

```bash
# macOS / Linux
chmod +x start.sh && ./start.sh
```

Handles venv creation, dependency install, FAISS index build, and server start automatically.

**Or manually:**

```bash
git clone https://github.com/shravan660/construction-pricing-api
cd construction-pricing-api
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
python scripts/build_index.py --use-seed
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

API live at **http://localhost:8000** | Docs at **http://localhost:8000/docs**

---

## Future Improvements

* Add frontend UI for quote submission
* Integrate real-time market pricing APIs (Batiprix / OPPBTP)
* Deploy on AWS/GCP with Postgres
* Add authentication and rate limiting
* Use FAISS for feedback similarity matching (currently keyword overlap)
* Incremental FAISS index updates instead of full rebuild on each scrape