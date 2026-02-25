from fastapi import APIRouter, HTTPException, Query, Request
from typing import List, Dict, Any

from ... import storage
from ...rate_limit import limiter
from ...geo.loader import load_all_geojson, find_geo_by_keyword, point_from_aircraft
from ...precompute import get_cached
from ...geo_utils import dca_radial_range as _dca_radial_range

router = APIRouter(prefix="/sfra")


@router.get("/")
@limiter.limit("30/minute")
async def sfra_aircraft(request: Request, name: str = Query("sfra", description="keyword to find the SFRA geojson file, default 'sfra'")) -> Dict[str, Any]:
    # Return pre-computed result if available (instant response for all users)
    cached = get_cached("sfra")
    if cached:
        return cached

    shapes = find_geo_by_keyword(name)
    if not shapes:
        raise HTTPException(status_code=404, detail=f"No geo named like '{name}' found in geo directory")

    snap = storage.STORAGE.get_latest_snapshot() if storage.STORAGE else None
    if not snap:
        return {"aircraft": []}
    aircraft = snap.get("data", {}).get("pilots") or snap.get("data", {}).get("aircraft") or []

    inside: List[Dict[str, Any]] = []
    for a in aircraft:
        cid = a.get("cid") or a.get("callsign") or '<no-cid>'
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
            try:
                inside_match = shp.contains(pt) or shp.touches(pt)
            except Exception:
                inside_match = False
            if inside_match:
                # return the original aircraft dict plus matched geo properties and DCA radial/range
                dca = _dca_radial_range(pt.y, pt.x)
                inside.append({"aircraft": a, "matched_props": props, "dca": dca})
                break
            else:
                # Not strictly inside — record vicinity if within a small distance (default 5 NM)
                try:
                    # Allow overriding tolerance (in nautical miles) via geo properties
                    vic_nm = float(props.get("vicinity_nm", 5)) if props and props.get("vicinity_nm") is not None else 5.0
                except Exception:
                    vic_nm = 5.0
                # Convert nautical miles to degrees approximately (1 NM ~= 1/60 degree)
                tol_deg = vic_nm / 60.0
                try:
                    dist_deg = pt.distance(shp)
                except Exception:
                    dist_deg = None
                try:
                    if dist_deg is not None and dist_deg <= tol_deg:
                        # Record as vicinity (do not include in 'inside' list)
                        pass
                except Exception:
                    pass
    return {"aircraft": inside}
