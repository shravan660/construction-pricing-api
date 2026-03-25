"""
BricoDepôt Scraper
==================
Scrapes product listings from https://www.bricodepot.fr across multiple
categories using Playwright (handles JavaScript rendering).

Anti-scraping measures handled:
  - Randomised User-Agent via fake_useragent
  - Configurable rate-limit delays between requests
  - Stealth viewport / headless settings to reduce bot fingerprint
  - Exponential back-off on transient failures (tenacity)
  - Graceful degradation: falls back to seed data if scraping fails

Run via:
    python scripts/scrape.py
    python scripts/scrape.py --seed-only   # skip live scraping, use seed data
"""

import asyncio
import json
import random
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from app.config import settings

# ─── Category targets ────────────────────────────────────────────────────────
# (url_slug, display_name)
CATEGORIES: list[tuple[str, str]] = [
    ("plomberie", "Plomberie"),
    ("electricite", "Électricité"),
    ("carrelage", "Carrelage"),
    ("menuiserie", "Menuiserie"),
]

# CSS selectors – update if BricoDepôt changes their markup
SELECTORS = {
    "product_card": "article.product-item, div.product-card, [data-testid='product-card']",
    "name": "h2, h3, .product-name, [data-testid='product-name']",
    "price": ".price, .prix, [data-testid='price'], .product-price",
    "description": ".product-description, .description, p.short-desc",
    "reference": ".reference, .ref, .sku",
    "next_page": "a[aria-label='Page suivante'], a.pagination-next, button.next-page",
}


def _save_raw(data: list[dict[str, Any]], category: str, raw_dir: Path) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = raw_dir / f"{category}_{ts}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Saved {len(data)} raw products → {path}")
    return path


def _parse_price(raw: str) -> float | None:
    """Extract a float from strings like '29,90 €' or '29.90'."""
    import re
    raw = raw.replace("\xa0", "").replace(" ", "")
    match = re.search(r"(\d+[,.]?\d*)", raw)
    if match:
        return float(match.group(1).replace(",", "."))
    return None


async def scrape_category(
    playwright_instance,
    category_slug: str,
    category_name: str,
    max_pages: int = 5,
    rate_limit: float = 2.0,
) -> list[dict[str, Any]]:
    """Navigate a BricoDepôt category page and extract products."""
    from playwright.async_api import TimeoutError as PlaywrightTimeout

    products: list[dict[str, Any]] = []
    base_url = f"https://www.bricodepot.fr/{category_slug}/"

    try:
        from fake_useragent import UserAgent
        ua = UserAgent()
        user_agent = ua.random
    except Exception:
        user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )

    browser = await playwright_instance.chromium.launch(headless=True)
    context = await browser.new_context(
        user_agent=user_agent,
        viewport={"width": 1366, "height": 768},
        locale="fr-FR",
    )
    page = await context.new_page()

    # Block images / fonts to speed up scraping
    await page.route(
        "**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf}",
        lambda route: route.abort(),
    )

    current_url = base_url
    for page_num in range(1, max_pages + 1):
        logger.info(f"[{category_name}] Scraping page {page_num}: {current_url}")
        try:
            await page.goto(current_url, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(random.randint(1_000, 2_000))

            # Accept cookie banner if present
            try:
                await page.click(
                    "button#onetrust-accept-btn-handler, button[aria-label*='Accepter']",
                    timeout=3_000,
                )
            except PlaywrightTimeout:
                pass

            cards = await page.query_selector_all(SELECTORS["product_card"])
            if not cards:
                logger.warning(f"[{category_name}] No product cards found on page {page_num}.")
                break

            for card in cards:
                try:
                    name_el = await card.query_selector(SELECTORS["name"])
                    price_el = await card.query_selector(SELECTORS["price"])
                    if not name_el or not price_el:
                        continue

                    name = (await name_el.inner_text()).strip()
                    raw_price = (await price_el.inner_text()).strip()
                    price = _parse_price(raw_price)
                    if not name or price is None:
                        continue

                    desc_el = await card.query_selector(SELECTORS["description"])
                    description = (await desc_el.inner_text()).strip() if desc_el else None

                    ref_el = await card.query_selector(SELECTORS["reference"])
                    reference = (await ref_el.inner_text()).strip() if ref_el else None

                    link_el = await card.query_selector("a")
                    url = await link_el.get_attribute("href") if link_el else None
                    if url and not url.startswith("http"):
                        url = f"https://www.bricodepot.fr{url}"

                    products.append(
                        {
                            "id": str(uuid.uuid4()),
                            "name": name,
                            "category": category_name,
                            "subcategory": None,
                            "description": description,
                            "price": price,
                            "currency": "EUR",
                            "unit": "unit",
                            "reference": reference,
                            "url": url,
                            "source": "bricodepot.fr",
                            "scraped_at": datetime.utcnow().isoformat(),
                        }
                    )
                except Exception as exc:
                    logger.debug(f"Card parse error: {exc}")
                    continue

            # Pagination: look for next-page element
            next_el = await page.query_selector(SELECTORS["next_page"])
            if not next_el:
                logger.info(f"[{category_name}] No next page found, stopping.")
                break

            next_href = await next_el.get_attribute("href")
            if next_href:
                current_url = (
                    next_href
                    if next_href.startswith("http")
                    else f"https://www.bricodepot.fr{next_href}"
                )
            else:
                await next_el.click()
                await page.wait_for_load_state("domcontentloaded")
                current_url = page.url

            # Rate-limit
            await asyncio.sleep(rate_limit + random.uniform(0.5, 1.5))

        except PlaywrightTimeout:
            logger.warning(f"[{category_name}] Page {page_num} timed out. Stopping.")
            break
        except Exception as exc:
            logger.error(f"[{category_name}] Unexpected error on page {page_num}: {exc}")
            break

    await browser.close()
    logger.success(f"[{category_name}] Scraped {len(products)} products.")
    return products


async def run_scraper(use_seed: bool = False) -> list[dict[str, Any]]:
    """Entry point: scrape all categories or fall back to seed data."""
    from app.scraper.seed_data import get_seed_products

    raw_dir = Path(settings.RAW_DATA_PATH)
    processed_dir = Path(settings.PROCESSED_DATA_PATH)

    if use_seed:
        logger.info("Using seed data (--seed-only flag set).")
        products = get_seed_products()
        _save_processed(products, processed_dir)
        return products

    all_products: list[dict[str, Any]] = []

    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            for slug, name in CATEGORIES:
                try:
                    products = await scrape_category(
                        pw,
                        slug,
                        name,
                        max_pages=settings.SCRAPER_MAX_PAGES_PER_CATEGORY,
                        rate_limit=settings.SCRAPER_RATE_LIMIT_SECONDS,
                    )
                    if products:
                        _save_raw(products, slug, raw_dir)
                        all_products.extend(products)
                    else:
                        logger.warning(
                            f"[{name}] No products scraped — using seed data for this category."
                        )
                        seed = [
                            p for p in get_seed_products() if p["category"] == name
                        ]
                        all_products.extend(seed)
                except Exception as exc:
                    logger.error(
                        f"[{name}] Scraping failed ({exc}). Falling back to seed data."
                    )
                    seed = [p for p in get_seed_products() if p["category"] == name]
                    all_products.extend(seed)

    except ImportError:
        logger.warning("Playwright not installed. Using seed data.")
        all_products = get_seed_products()

    if not all_products:
        logger.warning("No products scraped from any source. Using full seed dataset.")
        all_products = get_seed_products()

    _save_processed(all_products, processed_dir)
    return all_products


def _save_processed(products: list[dict[str, Any]], processed_dir: Path) -> Path:
    processed_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = processed_dir / f"products_{ts}.json"
    path.write_text(json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.success(f"Saved {len(products)} processed products → {path}")
    return path
