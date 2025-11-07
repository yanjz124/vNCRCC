from fastapi import APIRouter, Query, HTTPException
from typing import Any, Dict
import time
import urllib.request
import urllib.parse
import json
from vncrcc.geo import raster_elevation

router = APIRouter(prefix="/elevation")

# Simple in-memory cache: key -> (elevation_m, timestamp)
_CACHE: Dict[str, Any] = {}
_TTL = 60 * 60 * 6  # 6 hours


def _cache_key(lat: float, lon: float) -> str:
    # round to 4 decimals (~11m) to reduce calls
    return f"{round(lat,4)}:{round(lon,4)}"


@router.get("/")
async def elevation(lat: float = Query(...), lon: float = Query(...)) -> Dict[str, Any]:
    key = _cache_key(lat, lon)
    now = time.time()
    ent = _CACHE.get(key)
    if ent and now - ent[1] < _TTL:
        return {"elevation_m": ent[0], "cached": True}

    # Use local raster data only. If raster support isn't available, or no data
    # exists for the requested point, return a helpful HTTP error. This makes
    # the elevation provider fully internal and avoids external network calls.
    if not getattr(raster_elevation, "RASTER_AVAILABLE", False):
        raise HTTPException(
            status_code=503,
            detail=(
                "Local raster elevation not available. "
                "Install 'rasterio' and ensure 'src/vncrcc/geo/rasters_COP30.tar' is present and extracted."
            ),
        )

    try:
        elev_local = raster_elevation.sample_elevation(lat, lon)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Error sampling local raster: {exc}")

    if elev_local is None:
        # no data at this location in the provided rasters
        raise HTTPException(status_code=404, detail="No elevation data available at this location in local rasters")

    _CACHE[key] = (float(elev_local), now)
    return {"elevation_m": float(elev_local), "cached": False, "source": "local-raster"}
