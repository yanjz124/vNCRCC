from fastapi import APIRouter, HTTPException
from typing import Any, Dict

from ... import storage
from ...aircraft_history import get_history

router = APIRouter(prefix="/aircraft")


@router.get("/latest")
async def latest_aircraft() -> Dict[str, Any]:
    snap = storage.STORAGE.get_latest_snapshot() if storage.STORAGE else None
    if not snap:
        raise HTTPException(status_code=404, detail="No snapshot available")
    return snap


@router.get("/list")
async def list_aircraft() -> Dict[str, Any]:
    # Return pre-computed trimmed aircraft list from cache for instant response
    from ...precompute import get_cached
    cached = get_cached("aircraft_list")
    if cached:
        return {"aircraft": cached.get("aircraft", [])}
    # Fallback to full snapshot if cache not available
    aircraft_list = storage.STORAGE.list_aircraft() if storage.STORAGE else []
    return {"aircraft": aircraft_list}


@router.get("/list/history")
async def aircraft_history() -> Dict[str, Any]:
    return get_history()
