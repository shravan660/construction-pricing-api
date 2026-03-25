"""
FastAPI application entry point.

Startup sequence:
  1. Create all DB tables (idempotent)
  2. Ingest seed/scraped products into DB if empty
  3. Build (or load) FAISS index
  4. Mount all routers
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.api.routes import feedback, health, price, search
from app.config import settings
from app.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once at startup and once at shutdown."""
    # ── Startup ──────────────────────────────────────────────────────────────
    logger.info(f"Starting {settings.APP_NAME} v{settings.VERSION}")

    # 1. Create tables
    init_db()
    logger.info("Database tables ready.")

    # 2. Seed products into DB (only if table is empty)
    _ensure_products_in_db()

    # 3. Pre-warm the FAISS index (avoids cold-start on first /price request)
    try:
        from app.search.vector_store import _load_index
        _load_index()
        logger.success("Vector index pre-warmed.")
    except FileNotFoundError:
        logger.warning(
            "No FAISS index found on disk. "
            "Run  python scripts/build_index.py  to create it."
        )

    yield  # application runs

    # ── Shutdown ─────────────────────────────────────────────────────────────
    logger.info("Shutting down.")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.VERSION,
        description=(
            "Pricing Engine for construction/renovation proposals. "
            "Semantic material matching via FAISS + labour-rate task pricing."
        ),
        lifespan=lifespan,
    )

    # CORS — origins controlled via ALLOWED_ORIGINS env var (comma-separated)
    # Defaults to localhost for local dev; set explicitly in production
    allowed_origins = (
        [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
        if settings.ALLOWED_ORIGINS
        else ["http://localhost", "http://localhost:8000"]
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization"],
    )

    # Routers
    app.include_router(health.router)
    app.include_router(search.router)
    app.include_router(price.router)
    app.include_router(feedback.router)

    return app


app = create_app()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _ensure_products_in_db() -> None:
    """
    Load processed JSON files (or seed data) into the products table
    if it is empty.
    """
    from app.database import SessionLocal
    from app.models.db_models import Product
    from app.scraper.seed_data import get_seed_products

    db = SessionLocal()
    try:
        count = db.query(Product).count()
        if count > 0:
            logger.info(f"Products table already populated ({count} rows). Skipping ingest.")
            return

        # Try loading from processed JSON files first
        products = _load_processed_products()
        if not products:
            logger.info("No processed data found. Loading seed data.")
            products = get_seed_products()

        rows = [
            Product(
                id=p["id"],
                name=p["name"],
                category=p["category"],
                subcategory=p.get("subcategory"),
                description=p.get("description"),
                price=p["price"],
                currency=p.get("currency", "EUR"),
                unit=p.get("unit", "unit"),
                reference=p.get("reference"),
                url=p.get("url"),
                source=p.get("source", "seed_data"),
            )
            for p in products
        ]
        db.bulk_save_objects(rows)
        db.commit()
        logger.success(f"Inserted {len(rows)} products into the database.")
    finally:
        db.close()


def _load_processed_products() -> list[dict]:
    import json

    processed_dir = Path(settings.PROCESSED_DATA_PATH)
    if not processed_dir.exists():
        return []

    files = sorted(processed_dir.glob("products_*.json"), reverse=True)
    if not files:
        return []

    latest = files[0]
    logger.info(f"Loading processed products from {latest}")
    return json.loads(latest.read_text(encoding="utf-8"))
