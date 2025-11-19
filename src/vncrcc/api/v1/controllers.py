"""Controller activity API endpoint."""
from fastapi import APIRouter, Request
from ...controller_activity import fetch_zdc_controllers
from ...rate_limit import limiter

router = APIRouter(prefix="/controllers", tags=["controllers"])


@router.get("/")
@limiter.limit("12/minute")
async def get_controllers(request: Request) -> dict:
    """
    Return currently active ZDC controllers from vNAS.
    
    Filters for artccId=ZDC and primaryFacilityId in {PCT, DCA, NYG, ZDC, ADW}.
    Fetched independently from VATSIM data.
    """
    controllers = await fetch_zdc_controllers()
    
    return {
        "controllers": controllers,
        "count": len(controllers),
    }
