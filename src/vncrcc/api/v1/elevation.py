from fastapi import APIRouter, Query, HTTPException
from typing import Any, Dict
import time
import urllib.request
import urllib.parse
import json

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

    # call open-meteo elevation API
    try:
        base = "https://api.open-meteo.com/v1/elevation"
        qs = urllib.parse.urlencode({"latitude": lat, "longitude": lon})
        with urllib.request.urlopen(f"{base}?{qs}", timeout=5) as resp:
            body = resp.read()
        j = json.loads(body)
        elev = None
        if isinstance(j, dict) and "elevation" in j:
            # open-meteo returns an array even for a single coordinate: {"elevation": [87.0]}
            val = j.get("elevation")
            if isinstance(val, list):
                if not val:
                    raise ValueError("empty elevation array in response")
                elev = val[0]
            else:
                elev = val
        # fallback: older formats or other providers
        if elev is None and isinstance(j.get("data"), list) and j.get("data"):
            elev = j.get("data")[0].get("elevation")
        if elev is None:
            raise ValueError("no elevation in response")
        _CACHE[key] = (float(elev), now)
        return {"elevation_m": float(elev), "cached": False}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
