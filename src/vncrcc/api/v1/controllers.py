"""Controller activity API endpoint."""
from fastapi import APIRouter, Request
from ...controller_activity import fetch_zdc_controllers
from ...rate_limit import limiter

router = APIRouter(prefix="/controllers", tags=["controllers"])


@router.get("/")
@limiter.limit("30/minute")
async def get_controllers(request: Request) -> dict:
    """
    Return currently active ZDC controllers from vNAS.
    
    Filters for artccId=ZDC and primaryFacilityId in {PCT, DCA, NYG, ZDC, ADW}.
    Fetched independently from VATSIM data and cached server-side.
    """
    from ...precompute import get_cached
    
    # Return pre-computed result if available (instant response for all users)
    cached = get_cached("controllers")
    if cached:
        return cached
    
    # Fallback to live fetch if cache not available (e.g., on startup)
    controllers = await fetch_zdc_controllers()
    
    return {
        "controllers": controllers,
        "count": len(controllers),
    }
