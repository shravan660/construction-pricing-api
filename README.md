# Pricing Engine for Construction Quotes

A REST API that takes a construction proposal (tasks + materials) and returns realistic, market-informed prices. Built as a take-home assignment — the goal was to go from zero to something actually working in 48 hours, so some corners were cut deliberately, but the core pipeline is solid.

What it does:
- Scrapes real product data from [bricodepot.fr](https://www.bricodepot.fr)
- Uses multilingual semantic search (FAISS + sentence-transformers) to match materials
- Prices labor tasks using a formula based on published French market rates
- Applies regional multipliers, contractor margin, and a feedback adjustment loop

---

## How I approached this

My first thought was: the hardest part is the materials pricing, because you can't do exact-string matching against a catalog when contractors describe things in natural language (sometimes French, sometimes English, sometimes a mix). So I anchored the whole architecture around semantic search — get that right and everything else composites on top of it.

The rough order I built things:
1. Got the scraper working first so I had real data. BricoDepôt blocks straightforward `requests` calls, so I used Playwright. The scraper is a bit fragile (their DOM changes), but it runs and I built in fallback seed data so the index always builds even if scraping fails.
2. Built the embedding + FAISS layer. Chose `paraphrase-multilingual-MiniLM-L12-v2` specifically because the queries come in French and the catalog is in French, but the assignment examples were in English — needed something that handles both without fuss.
3. Wired up the FastAPI routes once the core search worked.
4. Added the task pricer separately — tasks don't exist in any catalog, so I went with a transparent formula rather than pretending I had "data" for it.
5. Feedback loop last, once everything else was stable.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                     PRICING ENGINE SYSTEM                           │
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐  │
│  │   Scraper    │───▶│  Embedder    │───▶│   FAISS Index        │  │
│  │ Playwright + │    │ MiniLM-L12   │    │  IndexFlatIP         │  │
│  │  seed data   │    │  (384-dim)   │    │  products.index      │  │
│  └──────────────┘    └──────────────┘    └──────────────────────┘  │
│                                                    │                │
│  ┌──────────────────────────────────────────────── ▼ ───────────┐  │
│  │                    FastAPI REST API                           │  │
│  │                                                               │  │
│  │  POST /price   ──▶  Material Pricer (semantic search)         │  │
│  │                 ──▶  Task Pricer    (labor-rate formula)       │  │
│  │                 ──▶  Modifiers      (regional + margin)        │  │
│  │                                                               │  │
│  │  POST /feedback ──▶  Feedback Engine (time-decay weighting)   │  │
│  │  GET  /search   ──▶  Raw vector search                        │  │
│  │  GET  /health   ──▶  Status + index info                      │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    SQLite (via SQLAlchemy)                    │   │
│  │   products │ feedback │ pricing_logs                         │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### Data flow (end to end)

1. **Scraper** (`scripts/scrape.py`) → crawls BricoDepôt, saves JSON to `data/processed/`
2. **Index builder** (`scripts/build_index.py`) → embeds all products, writes FAISS index + metadata JSON to disk
3. **API startup** → loads FAISS index into memory, seeds SQLite from processed JSON if the table is empty
4. **POST /price** → per material: vector search → best match price → regional × feedback × margin; per task: rate × hours × phase factor × regional × margin
5. **POST /feedback** → stores contractor price correction, influences the next `/price` call for similar items

---

## Design decisions & trade-offs

**Why FAISS instead of a vector database like Pinecone or Weaviate?**  
Zero infrastructure for the reviewer to set up. FAISS runs in-process with no docker dependencies and `IndexFlatIP` does exact cosine search — more than fast enough for a catalog of a few thousand products. If this were going to production with 500k+ products I'd switch to `IndexIVFFlat` or HNSW.

**Why `paraphrase-multilingual-MiniLM-L12-v2`?**  
The proposals can come in English or French (the assignment examples demonstrated this), and the catalog is entirely French. A standard English-only model would have killed match quality on French queries. The multilingual MiniLM is ~470 MB, CPU-friendly, and the 384-dim embeddings are fast enough to not be the bottleneck.

**Why SQLite?**  
Simplest possible setup. The ORM layer is SQLAlchemy so swapping to PostgreSQL is a single environment variable change — no code changes needed. For this use case (one API, one process, relatively low write volume) SQLite with WAL mode is perfectly adequate.

**Task pricing formula vs. something fancier**  
Tasks (labor) don't appear in any product catalog. I could have called an LLM for each task, but that adds latency, cost, and a hard external dependency. Instead I used published French market rates (Batiprix / OPPBTP) as the base and a phase-complexity multiplier. It's transparent — the `pricing_details` field shows exactly how the number was calculated — and it's adjustable via the feedback loop.

**Feedback grouping via keyword overlap**  
The "proper" solution here is to embed the feedback item labels and do a FAISS similarity search at adjustment time. I did the simpler thing: shared words > 3 chars. It works for the common case ("Cumulus 200L" matches "chauffe-eau 200L electrique") but obviously isn't great for synonyms with no shared words. This is the most obvious thing I'd improve with more time.

---

## Tech Stack

| Component | Choice | Why |
|-----------|--------|-----|
| Language | Python 3.11 | Best ecosystem for ML + web in this use case |
| Framework | FastAPI | Async, automatic OpenAPI docs, Pydantic validation out of the box |
| Embedding model | `paraphrase-multilingual-MiniLM-L12-v2` | French + English queries, 384-dim, runs on CPU, ~470 MB |
| Vector search | FAISS `IndexFlatIP` | No infra to set up, exact search, scales fine to ~500k products |
| Database | SQLite via SQLAlchemy | Zero-config, one env var to switch to Postgres |
| Scraper | Playwright (headless Chromium) | BricoDepôt renders product prices with JS — plain requests don't work |
| Container | Docker multi-stage | Smaller final image; FAISS index pre-built at build time so cold start is instant |

---

## Quick Start (local, no Docker)

**Prerequisites:** Python 3.11+

### One command (recommended)

```bash
# 1. Clone
git clone <your-repo-url>
cd pricing-engine

# 2. Run the startup script — it handles venv, deps, index build, and server start
```

**Windows (PowerShell):**
```powershell
.\start.ps1
```

**macOS / Linux:**
```bash
chmod +x start.sh && ./start.sh
```

That's it. The API will be live at **http://localhost:8000**  
Interactive docs: **http://localhost:8000/docs**

---

### Manual steps (if you prefer)

```bash
# Create and activate venv
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Build the FAISS index (uses built-in seed data — no scraping needed)
python scripts/build_index.py --use-seed

# Start the API
uvicorn app.main:app --port 8000
```

> **Windows long-path note:** If `pip install` fails with a path error, run this once as Administrator then reopen your terminal:
> ```powershell
> reg add "HKLM\SYSTEM\CurrentControlSet\Control\FileSystem" /v LongPathsEnabled /t REG_DWORD /d 1 /f
> ```

### With live scraping (optional)

```bash
# Install Playwright browser
python scripts/scrape.py --install-pw

# Run the scraper (Plomberie, Électricité, Carrelage, Menuiserie)
python scripts/scrape.py

# Rebuild index from fresh scraped data
python scripts/build_index.py

# Start the API
uvicorn app.main:app --reload
```

> **Anti-scraping note:** BricoDepôt occasionally returns empty results or challenges. The scraper falls back to seed data per category if scraping fails. Rate limiting is configurable via `SCRAPER_RATE_LIMIT_SECONDS` (default 2s + random jitter).

---

## Docker

```bash
# Build and start (index pre-built from seed data inside the image)
docker compose up --build

# Or separately:
docker build -t pricing-engine .
docker run -p 8000:8000 -v pricing_data:/app/data pricing-engine
```

---

## API Reference

### `POST /price`

Price a construction proposal.

```bash
curl -X POST http://localhost:8000/price \
  -H "Content-Type: application/json" \
  -d @tests/sample_payloads/water_heater.json
```

**Response fields per material:**

| Field | Meaning |
|-------|---------|
| `matched_product` | The catalog product the label was matched to |
| `confidence_score` | Cosine similarity (0–1) — higher is a better match |
| `base_cost` | `unit_price × quantity` after regional modifier |
| `feedback_adjustment` | EUR delta from historical contractor feedback |
| `adjusted_cost` | `base_cost + feedback_adjustment` |
| `with_margin` | `adjusted_cost × (1 + contractor_margin)` |
| `alternatives` | Up to 3 other candidate matches |

**Response fields per task:**

| Field | Meaning |
|-------|---------|
| `pricing_method` | Always `labor_rate_estimation` for tasks |
| `pricing_details` | Shows the exact formula used |
| `estimated_unit_price` | `hourly_rate × hours × phase_complexity × regional` |

### `POST /feedback`

```bash
curl -X POST http://localhost:8000/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "proposal_id": "test_001",
    "item_type": "material",
    "item_label": "Cumulus 200L",
    "feedback_type": "too_low",
    "actual_price": 350.00,
    "comment": "Prices have risen."
  }'
```

`feedback_type` accepts: `too_low`, `too_high`, `correct`

### `GET /search?q={query}&top_k={k}`

```bash
curl "http://localhost:8000/search?q=chauffe-eau+200L&top_k=3"
```

### `GET /health`

```bash
curl http://localhost:8000/health
```

---

## Task Pricing Logic

```
unit_price = hourly_rate(category) × hours(duration) × phase_factor(phase) × regional_modifier
```

Rates are seeded from Batiprix / OPPBTP 2024 published indices:

| Category | Rate (€/h) |
|----------|-----------|
| Plomberie | 45 |
| Électricité | 50 |
| Carrelage | 35 |
| Menuiserie | 40 |
| Default | 35 |

| Phase | Complexity Factor |
|-------|-----------------|
| Demo / Dépose | 0.75 |
| Prep | 0.80 |
| Install (default) | 1.00 |
| Finish / Finition | 1.10 |

Duration parsing handles French and English: `"2 heures"`, `"1 jour"`, `"3h"`, `"2 days"`, `"30 minutes"`.

---

## Feedback System

Feedback is stored in SQLite with a timestamp. Adjustments are computed as a time-decayed weighted average:

```
weight_i = exp(−λ × days_since_feedback_i)    (λ = 0.1 by default)
adjustment = Σ(weight_i × delta_i) / Σ(weight_i)
```

where `delta_i = actual_price_i − base_price`.

- Feedback from 1 day ago → weight ≈ 0.90
- Feedback from 7 days ago → weight ≈ 0.50
- Feedback from 30 days ago → weight ≈ 0.05

"Similar items" grouping uses keyword overlap (shared meaningful words). So feedback on `"Cumulus 200L"` also influences `"chauffe-eau 200L"`.

---

## Challenges faced

**BricoDepôt anti-scraping.** Their site uses JS rendering and rate-limits aggressively. I ended up using Playwright (headless Chromium) which adds a lot of install weight but actually works. I also built in seed data so the service is never blocked on scraping — you can run the full API without ever touching their site.

**Cross-language matching.** The proposal examples in the assignment were in English but the catalog is in French. Standard models would have low confidence on cross-language queries. The multilingual MiniLM solved this cleanly — "water heater connection kit" correctly matches "kit de raccordement chauffe-eau" with reasonable confidence.

**Task pricing without real data.** There's no catalog for labor. I looked at a few approaches — calling an LLM per task, scraping Batiprix, building a lookup table. I went with the formula approach because it's fast, deterministic, explainable, and integrates naturally with the feedback loop. The downside is rates are static unless updated manually.

**Duration parsing.** The duration field comes in as a free-text string from the upstream AI pipeline — "2 heures", "1 jour", "3h", "half day". I wrote a regex parser that handles the common patterns in both languages. It'll break on something unexpected, but for the realistic use case it covers everything in the sample payloads.

---

## Known limitations

| Limitation | Notes |
|-----------|-------|
| Scraper tied to BricoDepôt's DOM | Their HTML changes and the scraper breaks. Would need CSS selector config + fallback to their search API |
| Feedback groups by keyword overlap | Works for synonyms with shared words; misses things like "cumulus" ↔ "chauffe-eau" unless they share a word |
| SQLite single-writer | Fine for this scale. One env var swap to Postgres for production |
| Task rates are static | Seeded from Batiprix estimates, not live data |
| No authentication | All endpoints are open — would need API key middleware or OAuth2 for production |
| FAISS index is full-rebuild | No incremental upsert. Re-running the scraper re-indexes everything |
| Regional modifier table is hand-curated | Should pull from INSEE construction cost index API |

---

## If I had more time

- **Better feedback matching**: use FAISS to find semantically similar feedback items instead of keyword overlap. A feedback record for "Cumulus 200L" should influence "chauffe-eau electrique 200L vertical" even with no shared words.
- **Live task rate data**: integrate Batiprix PDF parsing or the OPPBTP API properly instead of hardcoding estimates.
- **Incremental scraping**: maintain a product ID → FAISS vector mapping and only re-embed new/changed products.
- **Confidence threshold UI**: right now low-confidence matches (< 0.5) still return a price. Should surface a "low-confidence" flag more prominently.
- **Auth**: API key middleware would be a 30-minute job, just didn't want to add complexity for the reviewer.
- **Tests for feedback endpoint**: the test suite covers pricing and search well but has zero coverage of `/feedback`.

---

## Database Schema

```sql
products (id, name, category, subcategory, description, price, currency,
          unit, reference, url, source, is_active, scraped_at)

feedback (id, proposal_id, item_type, item_label, feedback_type,
          expected_price, actual_price, comment, created_at)

pricing_logs (id, proposal_id, item_label, item_type, base_price,
              regional_modifier, feedback_adjustment, adjusted_cost,
              margin_applied, final_price, matched_product_id,
              confidence_score, pricing_method, pricing_details, created_at)
```

---

## Running Tests

```bash
# Index must be built first
python scripts/build_index.py --use-seed
pytest tests/ -v
```

---

## Project Structure

```
.
├── app/
│   ├── main.py                  # FastAPI app + lifespan hooks
│   ├── config.py                # Settings (pydantic-settings)
│   ├── database.py              # SQLAlchemy engine + session factory
│   ├── models/
│   │   ├── db_models.py         # SQLAlchemy ORM tables
│   │   └── schemas.py           # Pydantic request/response models
│   ├── scraper/
│   │   ├── bricodepot_scraper.py  # Playwright-based scraper
│   │   └── seed_data.py           # 60+ fallback products (so the API always works)
│   ├── search/
│   │   ├── embedder.py          # sentence-transformers wrapper
│   │   └── vector_store.py      # FAISS index build + search
│   ├── pricing/
│   │   ├── material_pricer.py   # Semantic search → price
│   │   ├── task_pricer.py       # Labor-rate formula
│   │   └── modifiers.py         # Regional multipliers + margin
│   ├── feedback/
│   │   └── feedback_engine.py   # Store + compute time-decayed adjustments
│   └── api/routes/
│       ├── price.py             # POST /price
│       ├── feedback.py          # POST /feedback
│       ├── search.py            # GET /search
│       └── health.py            # GET /health
├── scripts/
│   ├── scrape.py                # Run scraper
│   └── build_index.py           # Build FAISS index
├── tests/
│   ├── test_api.py              # Integration tests
│   └── sample_payloads/         # JSON test payloads
├── data/
│   ├── raw/                     # Raw scraped JSON
│   ├── processed/               # Cleaned JSON ready for indexing
│   └── indexes/                 # FAISS index + metadata JSON
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```
