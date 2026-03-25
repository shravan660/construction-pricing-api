from datetime import datetime

from fastapi import APIRouter
from sqlalchemy.orm import Session

from app.config import settings
from app.models.schemas import HealthResponse
from app.search.vector_store import index_size, is_index_loaded

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["Ops"])
def health_check():
    """Returns service status, index availability, and data counts."""
    # Lazy import to avoid circular dependency at startup
    from app.database import SessionLocal
    from app.feedback.feedback_engine import feedback_count
    from app.models.db_models import Product

    db: Session = SessionLocal()
    try:
        n_products = db.query(Product).count()
        n_feedback = feedback_count(db)
    finally:
        db.close()

    loaded = is_index_loaded()

    return HealthResponse(
        status="ok",
        version=settings.VERSION,
        index_loaded=loaded,
        product_count=n_products,
        feedback_count=n_feedback,
    )
