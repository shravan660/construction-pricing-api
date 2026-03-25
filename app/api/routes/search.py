from fastapi import APIRouter, Query

from app.config import settings
from app.models.schemas import SearchResponse, SearchResult
from app.search.vector_store import search

router = APIRouter()


@router.get("/search", response_model=SearchResponse, tags=["Search"])
def semantic_search(
    q: str = Query(..., description="Natural-language query (FR or EN)"),
    top_k: int = Query(default=5, ge=1, le=20, description="Number of results to return"),
):
    """
    Raw semantic search over the product catalogue.
    Useful for debugging, front-end autocomplete, or manual lookups.
    """
    hits = search(q, top_k=top_k)
    results = [
        SearchResult(
            product_id=h.get("id", ""),
            name=h["name"],
            category=h.get("category", ""),
            price=h["price"],
            unit=h.get("unit", "unit"),
            source=h.get("source", "bricodepot.fr"),
            confidence_score=h["confidence_score"],
            description=h.get("description"),
        )
        for h in hits
    ]
    return SearchResponse(query=q, top_k=top_k, results=results)
