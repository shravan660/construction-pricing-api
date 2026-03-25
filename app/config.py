from pathlib import Path
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).parent.parent


class Settings(BaseSettings):
    # ── App ──────────────────────────────────────────────────────────────────
    APP_NAME: str = "Pricing Engine API"
    VERSION: str = "1.0.0"
    DEBUG: bool = False

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str = f"sqlite:///{BASE_DIR}/data/pricing.db"

    # ── Vector Search ─────────────────────────────────────────────────────────
    EMBEDDING_MODEL: str = "paraphrase-multilingual-MiniLM-L12-v2"
    FAISS_INDEX_PATH: str = str(BASE_DIR / "data" / "indexes" / "products.index")
    PRODUCT_META_PATH: str = str(BASE_DIR / "data" / "indexes" / "products_meta.json")
    TOP_K_DEFAULT: int = 5

    # ── CORS ─────────────────────────────────────────────────────────────────
    # Comma-separated list of allowed origins, e.g. "https://app.example.com,https://admin.example.com"
    # Leave empty to default to localhost only
    ALLOWED_ORIGINS: str = ""

    # ── Feedback ──────────────────────────────────────────────────────────────
    # Exponential decay: weight = exp(-lambda * days_elapsed)
    FEEDBACK_DECAY_LAMBDA: float = 0.1

    # ── Scraper ───────────────────────────────────────────────────────────────
    SCRAPER_RATE_LIMIT_SECONDS: float = 2.0
    SCRAPER_MAX_PAGES_PER_CATEGORY: int = 5
    RAW_DATA_PATH: str = str(BASE_DIR / "data" / "raw")
    PROCESSED_DATA_PATH: str = str(BASE_DIR / "data" / "processed")

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
