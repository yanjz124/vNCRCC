from fastapi import APIRouter, Query
from typing import Any, Dict

from ... import storage

router = APIRouter(prefix="/incidents")


@router.get("/")
async def list_incidents(limit: int = Query(100, description="Maximum number of incidents to return")) -> Dict[str, Any]:
    """Return recent incidents persisted by the system."""
    items = storage.STORAGE.list_incidents(limit=limit) if storage.STORAGE else []
    return {"incidents": items, "count": len(items)}
