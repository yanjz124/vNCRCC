from fastapi import APIRouter, Request
from typing import Any, Dict
from ...rate_limit import limiter
from ...precompute import get_cached

router = APIRouter(prefix="/status")


@router.get("/")
@limiter.limit("30/minute")
async def system_status(request: Request) -> Dict[str, Any]:
    """Return system status including surge mode and processing metrics.
    
    Useful for monitoring server load and understanding current processing limits.
    """
    cached = get_cached("system_status")
    if not cached:
        return {
            "status": "initializing",
            "message": "System is starting up, no data processed yet"
        }
    
    return {
        "status": "operational",
        "surge_mode_active": cached.get("surge_mode", False),
        "total_aircraft_on_network": cached.get("total_aircraft_vatsim", 0),
        "aircraft_processed": cached.get("processed_aircraft", 0),
        "configured_radius_nm": cached.get("configured_radius_nm", 0),
        "effective_radius_nm": cached.get("effective_radius_nm", 0),
        "last_update": cached.get("computed_at", 0),
        "message": "Surge mode reduces processing radius during high-traffic events to maintain performance"
    }
