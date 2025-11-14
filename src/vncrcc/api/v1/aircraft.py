from fastapi import APIRouter, HTTPException
from typing import Any, Dict

from ... import storage
from ...aircraft_history import update_history, get_history

router = APIRouter(prefix="/aircraft")


@router.get("/latest")
async def latest_aircraft() -> Dict[str, Any]:
    snap = storage.STORAGE.get_latest_snapshot() if storage.STORAGE else None
    if not snap:
        raise HTTPException(status_code=404, detail="No snapshot available")
    return snap


@router.get("/list")
async def list_aircraft() -> Dict[str, Any]:
    aircraft_list = storage.STORAGE.list_aircraft() if storage.STORAGE else []
    # Record history for all aircraft
    for ac in aircraft_list:
        cid = str(ac.get("cid") or ac.get("callsign") or "")
        if cid:
            lat = ac.get("latitude") or ac.get("lat")
            lon = ac.get("longitude") or ac.get("lon")
            alt = ac.get("altitude") or ac.get("alt")
            callsign = ac.get("callsign", "")
            if lat is not None and lon is not None:
                update_history(cid, {"lat": lat, "lon": lon, "alt": alt, "callsign": callsign})
    return {"aircraft": aircraft_list}


@router.get("/list/history")
async def aircraft_history() -> Dict[str, Any]:
    return get_history()
