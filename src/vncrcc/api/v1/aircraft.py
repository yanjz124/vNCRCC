from fastapi import APIRouter, HTTPException, Query, Request
from typing import Any, Dict, Optional

from ... import storage
from ...aircraft_history import get_history
from ...rate_limit import limiter

router = APIRouter(prefix="/aircraft")

# DCA coordinates for distance filtering
DCA_LAT = 38.8514403
DCA_LON = -77.0377214


def _haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in nautical miles between two coordinates."""
    from math import radians, sin, cos, sqrt, atan2
    R = 6371.0  # Earth radius in km
    
    lat1_r = radians(lat1)
    lon1_r = radians(lon1)
    lat2_r = radians(lat2)
    lon2_r = radians(lon2)
    
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    
    a = sin(dlat / 2)**2 + cos(lat1_r) * cos(lat2_r) * sin(dlon / 2)**2
    c = 2 * atan2(sqrt(a), sqrt(max(0, 1 - a)))
    
    km = R * c
    return km / 1.852  # Convert to nautical miles


@router.get("/latest")
@limiter.limit("30/minute")
async def latest_aircraft(request: Request) -> Dict[str, Any]:
    snap = storage.STORAGE.get_latest_snapshot() if storage.STORAGE else None
    if not snap:
        raise HTTPException(status_code=404, detail="No snapshot available")
    return snap


@router.get("/list")
@limiter.limit("30/minute")
async def list_aircraft(request: Request) -> Dict[str, Any]:
    # Return pre-computed trimmed aircraft list from cache for instant response
    from ...precompute import get_cached
    cached = get_cached("aircraft_list")
    if cached:
        return {
            "aircraft": cached.get("aircraft", []),
            "vatsim_update_timestamp": cached.get("vatsim_update_timestamp")
        }
    # Fallback to full snapshot if cache not available
    aircraft_list = storage.STORAGE.list_aircraft() if storage.STORAGE else []
    return {"aircraft": aircraft_list}


@router.get("/list/history")
@limiter.limit("30/minute")
async def aircraft_history(
    request: Request,
    range_nm: Optional[float] = Query(None, description="Filter by distance from DCA in nautical miles")
) -> Dict[str, Any]:
    full_history = get_history()
    
    # If no range filter specified, return full history
    if range_nm is None:
        return full_history
    
    # Filter history to only include aircraft within range
    filtered_history = {}
    history_data = full_history.get("history", {})
    
    # Get current aircraft list to check which are in range
    from ...precompute import get_cached
    cached = get_cached("aircraft_list")
    current_aircraft = cached.get("aircraft", []) if cached else []
    
    # Build set of CIDs that are currently within range
    cids_in_range = set()
    for ac in current_aircraft:
        lat = ac.get("latitude") or ac.get("lat") or ac.get("y")
        lon = ac.get("longitude") or ac.get("lon") or ac.get("x")
        if lat is not None and lon is not None:
            dist = _haversine_nm(DCA_LAT, DCA_LON, lat, lon)
            if dist <= range_nm:
                cid = str(ac.get("cid", ""))
                if cid:
                    cids_in_range.add(cid)
    
    # Filter history to only include aircraft in range
    for cid, positions in history_data.items():
        if cid in cids_in_range:
            filtered_history[cid] = positions
    
    return {"history": filtered_history}
