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
        # altitude: if present, treat similar to SFRA — only include aircraft at or below 18,000 ft
        alt = a.get("altitude") or a.get("alt")
        try:
            alt_val = float(alt) if alt is not None else None
        except Exception:
            alt_val = None
        # FRZ applies up to 17,999 ft; skip unknown altitude or above 17,999
        if alt_val is None or alt_val > 17999:
            continue

        for shp, props in shapes:
            matched = False
            gtype = getattr(shp, "geom_type", "")
            # Polygons: use contains/touches as before
            if gtype in ("Polygon", "MultiPolygon"):
                if shp.contains(pt) or shp.touches(pt):
                    matched = True
            # Lines: FRZ geo may be a LineString/MultiLineString; consider points within a small distance
            elif gtype in ("LineString", "MultiLineString"):
                # tolerance in degrees; allow overriding via geojson properties (e.g. "tolerance": 0.001)
                tol = 0.001
                try:
                    if props and "tolerance" in props:
                        tol = float(props.get("tolerance", tol))
                except Exception:
                    tol = 0.001
                try:
                    if pt.distance(shp) <= tol:
                        matched = True
                except Exception:
                    matched = False
            else:
                # fallback: use intersects (covers Points etc.)
                try:
                    if shp.contains(pt) or shp.touches(pt) or shp.intersects(pt):
                        matched = True
                except Exception:
                    matched = False

            if matched:
                inside.append({"aircraft": a, "matched_props": props})
                break
    return {"aircraft": inside}
