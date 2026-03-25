from __future__ import annotations
from typing import Any, List, Optional
from pydantic import BaseModel, Field


# ─── Inbound: Proposal Request ───────────────────────────────────────────────

class TaskInput(BaseModel):
    id: int
    label: str
    description: Optional[str] = None
    category: Optional[str] = None
    zone: Optional[str] = None
    phase: Optional[str] = None
    unit: Optional[str] = "unit"
    quantity: float = 1.0
    duration: Optional[str] = None


class MaterialInput(BaseModel):
    label: str
    unit: Optional[str] = "unit"
    quantity: float = 1.0
    usedIn: Optional[List[int]] = None


class ProposalMetadata(BaseModel):
    city: Optional[str] = None
    region: Optional[str] = None
    jobType: Optional[str] = None


class ProposalRequest(BaseModel):
    proposal_id: str
    metadata: Optional[ProposalMetadata] = None
    contractor_margin: float = Field(default=0.0, ge=0.0, le=1.0)
    tasks: List[TaskInput] = []
    materials: List[MaterialInput] = []


# ─── Outbound: Priced Items ───────────────────────────────────────────────────

class AlternativeProduct(BaseModel):
    product: str
    price: float
    confidence: float


class PricedMaterial(BaseModel):
    label: str
    matched_product: Optional[str] = None
    confidence_score: float = 0.0
    unit_price: float
    quantity: float
    base_cost: float
    regional_modifier: float = 1.0
    feedback_adjustment: float = 0.0
    adjusted_cost: float
    with_margin: float
    source: str = "bricodepot.fr"
    alternatives: List[AlternativeProduct] = []


class PricedTask(BaseModel):
    id: int
    label: str
    category: Optional[str] = None
    estimated_unit_price: float
    quantity: float
    base_cost: float
    feedback_adjustment: float = 0.0
    adjusted_cost: float
    with_margin: float
    pricing_method: str = "labor_rate_estimation"
    pricing_details: str = ""


class PricingSummary(BaseModel):
    materials_subtotal: float
    tasks_subtotal: float
    total: float
    avg_material_confidence: float
    pricing_metadata: dict[str, Any]


class ProposalResponse(BaseModel):
    proposal_id: str
    currency: str = "EUR"
    priced_materials: List[PricedMaterial]
    priced_tasks: List[PricedTask]
    summary: PricingSummary


# ─── Feedback ────────────────────────────────────────────────────────────────

class FeedbackRequest(BaseModel):
    proposal_id: str
    item_type: str = Field(..., pattern="^(material|task)$")
    item_label: str
    feedback_type: str = Field(..., pattern="^(too_low|too_high|correct)$")
    actual_price: Optional[float] = None
    comment: Optional[str] = None


class FeedbackResponse(BaseModel):
    status: str
    feedback_id: str
    message: str


# ─── Search ──────────────────────────────────────────────────────────────────

class SearchResult(BaseModel):
    product_id: str
    name: str
    category: str
    price: float
    unit: str
    source: str
    confidence_score: float
    description: Optional[str] = None


class SearchResponse(BaseModel):
    query: str
    top_k: int
    results: List[SearchResult]


# ─── Health ──────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    version: str
    index_loaded: bool
    product_count: int
    feedback_count: int
