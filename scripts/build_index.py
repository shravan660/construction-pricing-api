"""
scripts/build_index.py
──────────────────────
Build (or rebuild) the FAISS semantic search index from the
most recent processed products JSON.

Usage:
    python scripts/build_index.py               # use latest processed JSON
    python scripts/build_index.py --use-seed    # force-rebuild from seed data

The script also upserts products into SQLite so the DB and index
stay in sync.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger


def main():
    parser = argparse.ArgumentParser(description="Build FAISS product index")
    parser.add_argument(
        "--use-seed",
        action="store_true",
        help="Force rebuild using built-in seed data instead of processed files",
    )
    args = parser.parse_args()

    from app.config import settings
    from app.database import init_db, SessionLocal
    from app.models.db_models import Product
    from app.scraper.seed_data import get_seed_products
    from app.search.vector_store import build_index

    # ── Resolve product list ─────────────────────────────────────────────────
    products = []

    if not args.use_seed:
        processed_dir = Path(settings.PROCESSED_DATA_PATH)
        if processed_dir.exists():
            files = sorted(processed_dir.glob("products_*.json"), reverse=True)
            if files:
                logger.info(f"Loading products from {files[0].name}")
                products = json.loads(files[0].read_text(encoding="utf-8"))

    if not products:
        logger.info("No processed files found or --use-seed set. Using seed data.")
        products = get_seed_products()

    logger.info(f"Building index from {len(products)} products…")

    # ── Upsert into SQLite ───────────────────────────────────────────────────
    init_db()
    db = SessionLocal()
    try:
        existing_ids = {row.id for row in db.query(Product.id).all()}
        new_rows = [
            Product(
                id=p["id"],
                name=p["name"],
                category=p.get("category", ""),
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
            if p["id"] not in existing_ids
        ]
        if new_rows:
            db.bulk_save_objects(new_rows)
            db.commit()
            logger.info(f"Inserted {len(new_rows)} new products into SQLite.")
        else:
            logger.info("No new products to insert (all already in DB).")
    finally:
        db.close()

    # ── Build FAISS index ────────────────────────────────────────────────────
    build_index(products)
    logger.success("Index build complete. API is ready to serve requests.")


if __name__ == "__main__":
    main()
