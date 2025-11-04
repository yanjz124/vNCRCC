from fastapi import APIRouter, HTTPException
from typing import Any, Dict

from ... import storage

router = APIRouter(prefix="/aircraft")


@router.get("/latest")
async def latest_aircraft() -> Dict[str, Any]:
    snap = storage.STORAGE.get_latest_snapshot() if storage.STORAGE else None
    if not snap:
        raise HTTPException(status_code=404, detail="No snapshot available")
    return snap


@router.get("/list")
async def list_aircraft() -> Dict[str, Any]:
    return {"aircraft": storage.STORAGE.list_aircraft() if storage.STORAGE else []}
