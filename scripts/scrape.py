"""
scripts/scrape.py
─────────────────
Scrape product data from BricoDepôt and save to data/processed/.

Usage:
    python scripts/scrape.py                # live scrape (Playwright required)
    python scripts/scrape.py --seed-only    # skip live scraping, use seed data
    python scripts/scrape.py --install-pw   # install Playwright browsers first

After running, execute  python scripts/build_index.py  to rebuild the FAISS index.
"""
import argparse
import asyncio
import sys
from pathlib import Path

# Make sure the project root is on the path regardless of cwd
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger


def main():
    parser = argparse.ArgumentParser(description="BricoDepôt product scraper")
    parser.add_argument(
        "--seed-only",
        action="store_true",
        help="Skip live scraping and use built-in seed data",
    )
    parser.add_argument(
        "--install-pw",
        action="store_true",
        help="Install Playwright browsers before scraping",
    )
    args = parser.parse_args()

    if args.install_pw:
        import subprocess
        logger.info("Installing Playwright browsers…")
        subprocess.run(["playwright", "install", "chromium"], check=True)

    from app.scraper.bricodepot_scraper import run_scraper

    products = asyncio.run(run_scraper(use_seed=args.seed_only))
    logger.success(f"Scraping complete. {len(products)} products collected.")
    logger.info("Next step: python scripts/build_index.py")


if __name__ == "__main__":
    main()
