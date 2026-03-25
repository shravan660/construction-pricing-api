"""
Embedding generator using sentence-transformers.

Model choice: paraphrase-multilingual-MiniLM-L12-v2
  • 50+ languages including French and English
  • 384-dimensional embeddings
  • ~470MB, runs on CPU without issues
  • Strong cross-lingual semantic similarity (FR ↔ EN queries work well)
"""

from __future__ import annotations

import os
import ssl
import warnings

# ── Corporate proxy / SSL bypass ─────────────────────────────────────────────
# Must be set BEFORE any network library is imported.
# Accenture (and most enterprise) networks use SSL inspection proxies with
# self-signed certificates. This disables cert verification for HuggingFace
# model downloads only.
os.environ["CURL_CA_BUNDLE"] = ""
os.environ["REQUESTS_CA_BUNDLE"] = ""
os.environ["TRANSFORMERS_VERBOSITY"] = "error"
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"

# Patch Python's built-in SSL context
ssl._create_default_https_context = ssl._create_unverified_context

# Patch urllib3 / requests so HuggingFace Hub skips cert verification
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import requests as _requests
_orig_send = _requests.Session.send

def _patched_send(self, request, **kwargs):
    kwargs["verify"] = False
    return _orig_send(self, request, **kwargs)

_requests.Session.send = _patched_send

# ── Now safe to import model libraries ───────────────────────────────────────
import numpy as np
from loguru import logger
from sentence_transformers import SentenceTransformer

from app.config import settings

# Module-level singleton — loaded once, reused across requests
_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        logger.info(f"Loading embedding model: {settings.EMBEDDING_MODEL}")
        _model = SentenceTransformer(settings.EMBEDDING_MODEL)
        logger.success("Embedding model loaded.")
    return _model


def embed_texts(texts: list[str], batch_size: int = 64) -> np.ndarray:
    """
    Encode a list of strings into L2-normalised embeddings.
    Returns shape (N, 384) float32 array.
    """
    model = get_model()
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=len(texts) > 100,
        convert_to_numpy=True,
        normalize_embeddings=True,   # cosine sim via inner-product
    )
    return embeddings.astype(np.float32)


def embed_query(query: str) -> np.ndarray:
    """
    Encode a single query string.
    Returns shape (1, 384) float32 array ready for FAISS.
    """
    return embed_texts([query])
