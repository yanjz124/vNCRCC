"""Consolidated dashboard endpoint for efficient polling."""
from fastapi import APIRouter, Request, Query
from typing import Any, Dict, Optional
import time

from ... import storage
from ...aircraft_history import get_history
from ...p56_history import get_history as get_p56_history
from ...rate_limit import limiter

router = APIRouter(prefix="/dashboard")

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


@router.get("")
@limiter.limit("60/minute")  # Higher limit since it's one consolidated call
async def get_dashboard(
    request: Request,
    range_nm: Optional[float] = Query(None, description="Filter by distance from DCA in nautical miles"),
    include_history: bool = Query(True, description="Include aircraft history data")
) -> Dict[str, Any]:
    """
    Consolidated dashboard endpoint returning all data in one response.

    Returns:
    - aircraft: Current aircraft list (pre-computed and filtered)
    - history: Aircraft position history (optional, filtered by range)
    - controllers: Active ZDC controllers
    - vip: VIP aircraft detected
    - p56: P56 intrusion events and current intrusions
    - timestamp: Server timestamp of response
    """
    from ...precompute import get_cached

    start_time = time.time()
    response = {
        "aircraft": {},
        "history": {},
        "controllers": {},
        "vip": {},
        "p56": {},
        "timestamp": start_time
    }

    # Get snapshot for metadata
    snap = storage.STORAGE.get_latest_snapshot() if storage.STORAGE else None
    fetched_at = snap.get("fetched_at") if snap else None
    data = snap.get("data", {}) if snap else {}
    vatsim_ts = data.get("general", {}).get("update_timestamp") if snap else None

    # 1. Aircraft list (from precompute cache)
    cached = get_cached("aircraft_list")
    if cached:
        aircraft = cached.get("aircraft", [])

        # Apply user's VSO range filter if specified
        if range_nm is not None:
            filtered = []
            for ac in aircraft:
                lat = ac.get("latitude") or ac.get("lat") or ac.get("y")
                lon = ac.get("longitude") or ac.get("lon") or ac.get("x")
                if lat is not None and lon is not None:
                    dist = _haversine_nm(DCA_LAT, DCA_LON, lat, lon)
                    if dist <= range_nm:
                        filtered.append(ac)
            aircraft = filtered

        response["aircraft"] = {
            "list": aircraft,
            "vatsim_update_timestamp": cached.get("vatsim_update_timestamp"),
            "computed_at": cached.get("computed_at"),
            "count": len(aircraft)
        }
    else:
        # Fallback to full snapshot
        pilots = data.get("pilots") or data.get("aircraft") or []
        if range_nm is not None:
            filtered = []
            for ac in pilots:
                lat = ac.get("latitude") or ac.get("lat") or ac.get("y")
                lon = ac.get("longitude") or ac.get("lon") or ac.get("x")
                if lat is not None and lon is not None:
                    dist = _haversine_nm(DCA_LAT, DCA_LON, lat, lon)
                    if dist <= range_nm:
                        filtered.append(ac)
            pilots = filtered

        response["aircraft"] = {
            "list": pilots,
            "vatsim_update_timestamp": vatsim_ts,
            "fetched_at": fetched_at,
            "count": len(pilots)
        }

    # 2. Aircraft history (optional, can be expensive)
    if include_history:
        full_history = get_history()

        if range_nm is None:
            # Return full history
            response["history"] = {
                "data": full_history.get("history", {}),
                "fetched_at": fetched_at,
                "vatsim_update_timestamp": vatsim_ts,
                "filtered": False
            }
        else:
            # Filter history to aircraft currently in range
            history_data = full_history.get("history", {})
            current_aircraft = data.get("pilots") or data.get("aircraft") or []

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

            filtered_history = {cid: positions for cid, positions in history_data.items() if cid in cids_in_range}

            response["history"] = {
                "data": filtered_history,
                "fetched_at": fetched_at,
                "vatsim_update_timestamp": vatsim_ts,
                "filtered": True,
                "range_nm": range_nm
            }

    # 3. Controllers (from precompute cache)
    controllers_cached = get_cached("controllers")
    if controllers_cached:
        response["controllers"] = controllers_cached
    else:
        # Fallback to empty (will be populated on next fetch)
        response["controllers"] = {
            "controllers": [],
            "count": 0
        }

    # 4. VIP aircraft (from precompute cache)
    vip_cached = get_cached("vip_aircraft")
    if vip_cached:
        response["vip"] = vip_cached
    else:
        response["vip"] = {
            "aircraft": []
        }

    # 5. P56 breaches (match format of /api/v1/p56/ endpoint)
    p56_cached = get_cached("p56")
    if p56_cached:
        response["p56"] = {
            "breaches": p56_cached.get("aircraft", []),
            "history": get_p56_history(),
            "fetched_at": p56_cached.get("computed_at")
        }
    else:
        # Fallback if no cache available
        response["p56"] = {
            "breaches": [],
            "history": get_p56_history()
        }

    # Add processing time
    response["processing_time_ms"] = round((time.time() - start_time) * 1000, 2)

    return response
