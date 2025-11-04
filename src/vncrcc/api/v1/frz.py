from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Any

from ... import storage
from ...geo.loader import find_geo_by_keyword, point_from_aircraft

router = APIRouter(prefix="/frz")


@router.get("/")
async def frz_aircraft(name: str = Query("frz", description="keyword to find the FRZ geojson file, default 'frz'")) -> Dict[str, Any]:
    shapes = find_geo_by_keyword(name)
    if not shapes:
        raise HTTPException(status_code=404, detail=f"No geo named like '{name}' found in geo directory")

    snap = storage.STORAGE.get_latest_snapshot() if storage.STORAGE else None
    if not snap:
        return {"aircraft": []}
    aircraft = snap.get("data", {}).get("pilots") or snap.get("data", {}).get("aircraft") or []

    inside: List[Dict[str, Any]] = []
    for a in aircraft:
        pt = point_from_aircraft(a)
        if not pt:
            continue
        for shp, props in shapes:
            if shp.contains(pt):
                inside.append({"aircraft": a, "matched_props": props})
                break
    return {"aircraft": inside}
