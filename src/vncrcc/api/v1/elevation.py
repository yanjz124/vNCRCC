from fastapi import APIRouter, Query, HTTPException, Request
from typing import Any, Dict
import time
from vncrcc.geo import raster_elevation
from ...rate_limit import limiter

router = APIRouter(prefix="/elevation")

# Simple in-memory cache: key -> (elevation_m, timestamp)
_CACHE: Dict[str, Any] = {}
_TTL = 60 * 60 * 6  # 6 hours


def _cache_key(lat: float, lon: float) -> str:
    # round to 4 decimals (~11m) to reduce calls
    return f"{round(lat,4)}:{round(lon,4)}"


@router.get("/")
@limiter.limit("60/minute")
async def elevation(request: Request, lat: float = Query(...), lon: float = Query(...)) -> Dict[str, Any]:
    key = _cache_key(lat, lon)
    now = time.time()
    ent = _CACHE.get(key)
    if ent and now - ent[1] < _TTL:
        return {"elevation_m": ent[0], "cached": True}

    # Use local raster data only. If raster support isn't available or the
    # rasters don't contain the point, return a 200 JSON with elevation_m=null
    # and a clear source so clients can apply a deterministic fallback. This
    # keeps the service local-only while avoiding 503/404 responses that clutter
    # logs and complicate client error handling.
    if not getattr(raster_elevation, "RASTER_AVAILABLE", False):
        # Local sampling not available; return neutral response (no external calls)
        return {
            "elevation_m": None,
            "cached": False,
            "source": "none",
            "message": "Local raster support not available. Install rasterio and ensure local rasters are present for precise elevation."
        }

    try:
        elev_local = raster_elevation.sample_elevation(lat, lon)
    except Exception as exc:
        # Sampling failed; return neutral response rather than an HTTP error
        return {
            "elevation_m": None,
            "cached": False,
            "source": "error",
            "message": f"Error sampling local raster: {exc}"
        }

    if elev_local is None:
        # no data at this location in the provided rasters - return neutral
        return {"elevation_m": None, "cached": False, "source": "none", "message": "No local elevation data for this location"}

    _CACHE[key] = (float(elev_local), now)
    return {"elevation_m": float(elev_local), "cached": False, "source": "local-raster"}
