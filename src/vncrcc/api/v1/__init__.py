from fastapi import APIRouter

from . import aircraft, sfra, frz, p56, incidents, vso, geo, elevation, vip, controllers, status

router = APIRouter(prefix="/v1")
router.include_router(aircraft.router)
router.include_router(sfra.router)
router.include_router(frz.router)
router.include_router(p56.router)
router.include_router(incidents.router)
router.include_router(vso.router)
router.include_router(geo.router)
router.include_router(elevation.router)
router.include_router(vip.router)
router.include_router(controllers.router)
router.include_router(status.router)

__all__ = ["router"]
