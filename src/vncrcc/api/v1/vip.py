"""VIP activity API endpoint."""
from fastapi import APIRouter, Request
from ..storage import STORAGE
from ..vip_activity import detect_vip_aircraft
from ..rate_limit import limiter

router = APIRouter(prefix="/vip", tags=["vip"])


@router.get("/")
@limiter.limit("12/minute")
async def get_vip_activity(request: Request) -> dict:
    """
    Return currently active VIP aircraft on VATSIM network.
    
    Scans globally (no range restriction) for presidential and VP callsigns.
    Returns format similar to SFRA/FRZ endpoints.
    """
    snapshot = STORAGE.get_latest_snapshot()
    if not snapshot:
        return {"aircraft": [], "count": 0, "fetched_at": None}
    
    data = snapshot.get("data", {})
    fetched_at = snapshot.get("fetched_at")
    
    # Get all pilots (no geographic filter)
    pilots = data.get("pilots", [])
    
    # Detect VIP aircraft
    vip_aircraft = detect_vip_aircraft(pilots)
    
    return {
        "aircraft": vip_aircraft,
        "count": len(vip_aircraft),
        "fetched_at": fetched_at,
    }
