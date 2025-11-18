from fastapi import APIRouter, Query, HTTPException, Request
from typing import Any, Dict, List
from shapely.geometry import mapping

from ...geo.loader import find_geo_by_keyword
from ...rate_limit import limiter

router = APIRouter(prefix="/geo")


@router.get("/")
@limiter.limit("6/minute")
async def geo_features(request: Request, name: str = Query("", description="keyword to find geo files (e.g. sfra, frz, p56)")) -> Dict[str, Any]:
    if not name:
        raise HTTPException(status_code=400, detail="missing name parameter")
    shapes = find_geo_by_keyword(name)
    if not shapes:
        raise HTTPException(status_code=404, detail=f"No geo named like '{name}' found in geo directory")

    features: List[Dict[str, Any]] = []
    for shp, props in shapes:
        try:
            geom = mapping(shp)
            features.append({"type": "Feature", "geometry": geom, "properties": props or {}})
        except Exception:
            continue

    return {"type": "FeatureCollection", "features": features}
