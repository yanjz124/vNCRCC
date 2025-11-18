from fastapi import APIRouter, Query, Request
from typing import Any, Dict

from ... import storage
from ...rate_limit import limiter

router = APIRouter(prefix="/incidents")


@router.get("/")
@limiter.limit("6/minute")
async def list_incidents(request: Request, limit: int = Query(100, description="Maximum number of incidents to return")) -> Dict[str, Any]:
    """Return recent incidents persisted by the system."""
    items = storage.STORAGE.list_incidents(limit=limit) if storage.STORAGE else []
    return {"incidents": items, "count": len(items)}
