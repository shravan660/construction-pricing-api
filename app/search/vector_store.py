"""
FAISS vector store — build, persist, and search product embeddings.

Using IndexFlatIP (inner product on L2-normalised vectors = cosine similarity).
It's exact search with no approximation, which is fine for a catalog of a few
thousand products. If we ever got into the hundreds of thousands, I'd switch to
IndexIVFFlat with a trained coarse quantizer — but that's premature for now.

Index and metadata are written to disk so startup is fast (just mmap the file)
rather than re-embedding everything on every boot.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import faiss
import numpy as np
from loguru import logger

from app.config import settings
from app.search.embedder import embed_texts, embed_query

# ─── Module-level singletons (lazy-loaded) ───────────────────────────────────
_index: faiss.IndexFlatIP | None = None
_meta: list[dict[str, Any]] = []          # parallel list: meta[i] ↔ index vector i


# ─── Build ────────────────────────────────────────────────────────────────────

def build_index(products: list[dict[str, Any]]) -> None:
    """
    Embed all products and write the FAISS index + metadata to disk.
    products: list of dicts with keys id, name, category, description, price, …
    """
    global _index, _meta

    logger.info(f"Building FAISS index for {len(products)} products…")

    texts = [_product_text(p) for p in products]
    embeddings = embed_texts(texts)           # (N, 384) float32, already normalised

    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)

    # Persist
    index_path = Path(settings.FAISS_INDEX_PATH)
    meta_path = Path(settings.PRODUCT_META_PATH)
    index_path.parent.mkdir(parents=True, exist_ok=True)

    faiss.write_index(index, str(index_path))
    meta_path.write_text(
        json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    logger.success(
        f"Index saved → {index_path}  |  {len(products)} vectors, dim={dim}"
    )

    # Update in-memory state
    _index = index
    _meta = products


# ─── Load ─────────────────────────────────────────────────────────────────────

def _load_index() -> tuple[faiss.IndexFlatIP, list[dict[str, Any]]]:
    """Load index and metadata from disk (if not already in memory)."""
    global _index, _meta

    if _index is not None:
        return _index, _meta

    index_path = Path(settings.FAISS_INDEX_PATH)
    meta_path = Path(settings.PRODUCT_META_PATH)

    if not index_path.exists() or not meta_path.exists():
        raise FileNotFoundError(
            "Vector index not found. Run  python scripts/build_index.py  first."
        )

    logger.info("Loading FAISS index from disk…")
    _index = faiss.read_index(str(index_path))
    _meta = json.loads(meta_path.read_text(encoding="utf-8"))
    logger.success(f"Index loaded: {_index.ntotal} vectors.")
    return _index, _meta


def is_index_loaded() -> bool:
    try:
        _load_index()
        return True
    except FileNotFoundError:
        return False


def index_size() -> int:
    try:
        idx, _ = _load_index()
        return idx.ntotal
    except FileNotFoundError:
        return 0


# ─── Search ───────────────────────────────────────────────────────────────────

def search(query: str, top_k: int | None = None) -> list[dict[str, Any]]:
    """
    Semantic search over the product index.

    Returns a list of dicts, each containing product metadata plus
    a 'confidence_score' (inner-product similarity, 0–1 range).
    """
    if top_k is None:
        top_k = settings.TOP_K_DEFAULT

    index, meta = _load_index()

    query_vec = embed_query(query)                         # (1, 384)
    top_k = min(top_k, index.ntotal)
    distances, indices = index.search(query_vec, top_k)   # both shape (1, top_k)

    results = []
    for dist, idx in zip(distances[0], indices[0]):
        if idx < 0:
            continue
        product = dict(meta[idx])
        product["confidence_score"] = float(round(dist, 4))
        results.append(product)

    return results


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _product_text(p: dict[str, Any]) -> str:
    """Build the text string that gets embedded for a product."""
    parts = [p.get("name", "")]
    if p.get("category"):
        parts.append(p["category"])
    if p.get("subcategory"):
        parts.append(p["subcategory"])
    if p.get("description"):
        parts.append(p["description"])
    return " | ".join(filter(None, parts))
