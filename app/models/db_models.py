import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Float, Boolean, Text,
    DateTime, ForeignKey, Integer,
)
from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Product(Base):
    """A scraped product from BricoDepôt (or seed data)."""

    __tablename__ = "products"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False, index=True)
    category = Column(String, nullable=False, index=True)
    subcategory = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    price = Column(Float, nullable=False)
    currency = Column(String, default="EUR")
    unit = Column(String, default="unit")
    reference = Column(String, nullable=True)
    url = Column(String, nullable=True)
    source = Column(String, default="bricodepot.fr")
    is_active = Column(Boolean, default=True)
    scraped_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def embed_text(self) -> str:
        """Text used for generating the embedding (name + category + description)."""
        parts = [self.name, self.category]
        if self.subcategory:
            parts.append(self.subcategory)
        if self.description:
            parts.append(self.description)
        return " | ".join(parts)


class Feedback(Base):
    """Contractor price feedback used to adjust future pricing."""

    __tablename__ = "feedback"

    id = Column(String, primary_key=True, default=_uuid)
    proposal_id = Column(String, nullable=False, index=True)
    item_type = Column(String, nullable=False)          # 'material' | 'task'
    item_label = Column(String, nullable=False, index=True)
    feedback_type = Column(String, nullable=False)       # 'too_low' | 'too_high' | 'correct'
    expected_price = Column(Float, nullable=True)        # price the engine predicted
    actual_price = Column(Float, nullable=True)          # price the contractor paid
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class PricingLog(Base):
    """Audit trail for every priced item."""

    __tablename__ = "pricing_logs"

    id = Column(String, primary_key=True, default=_uuid)
    proposal_id = Column(String, nullable=False, index=True)
    item_label = Column(String, nullable=False)
    item_type = Column(String, nullable=False)           # 'material' | 'task'
    base_price = Column(Float, nullable=True)
    regional_modifier = Column(Float, default=1.0)
    feedback_adjustment = Column(Float, default=0.0)
    adjusted_cost = Column(Float, nullable=True)
    margin_applied = Column(Float, default=0.0)
    final_price = Column(Float, nullable=True)
    matched_product_id = Column(String, ForeignKey("products.id"), nullable=True)
    confidence_score = Column(Float, nullable=True)
    pricing_method = Column(String, nullable=True)
    pricing_details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
