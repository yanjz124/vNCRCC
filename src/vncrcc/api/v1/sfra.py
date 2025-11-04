from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Any

from ... import storage
from ...geo.loader import load_all_geojson, find_geo_by_keyword, point_from_aircraft

router = APIRouter(prefix="/sfra")


@router.get("/")
async def sfra_aircraft(name: str = Query("sfra", description="keyword to find the SFRA geojson file, default 'sfra'")) -> Dict[str, Any]:
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
        # altitude: require present and <= 18000 ft
        alt = a.get("altitude") or a.get("alt")
        try:
            alt_val = float(alt) if alt is not None else None
        except Exception:
            alt_val = None
        # SFRA applies up to 17,999 ft; skip unknown altitude or above 17,999
        if alt_val is None or alt_val > 17999:
            continue
        for shp, props in shapes:
            # treat points on the polygon boundary as inside as well
            if shp.contains(pt) or shp.touches(pt):
                # return the original aircraft dict plus matched geo properties
                inside.append({"aircraft": a, "matched_props": props})
                break
    return {"aircraft": inside}
