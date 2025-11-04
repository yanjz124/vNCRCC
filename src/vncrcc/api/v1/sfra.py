from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Any

from ... import storage
from ...geo.loader import load_all_geojson, find_geo_by_keyword, point_from_aircraft
import math

# DCA bullseye (lat, lon)
DCA_BULL = (38.8514403, -77.0377214)


def _dca_radial_range(lat: float, lon: float) -> dict:
    """Return bearing (degrees) and distance (nautical miles) from DCA to (lat,lon).

    Also return a compact string like 'DCA280010' (bearing 280 deg, range 10 nm).
    """
    lat1 = math.radians(DCA_BULL[0])
    lon1 = math.radians(DCA_BULL[1])
    lat2 = math.radians(lat)
    lon2 = math.radians(lon)

    dlon = lon2 - lon1
    # initial bearing from point1 to point2
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    brng = math.degrees(math.atan2(x, y))
    brng = (brng + 360) % 360

    # haversine distance
    R_km = 6371.0
    a = math.sin((lat2 - lat1) / 2.0) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1 - a)))
    dist_km = R_km * c
    dist_nm = dist_km / 1.852

    brng_i = int(round(brng)) % 360
    dist_i = int(round(dist_nm))
    compact = f"DCA{brng_i:03d}{dist_i:03d}"
    return {"radial_range": compact, "bearing": brng_i, "range_nm": dist_i}

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
            try:
                inside_match = shp.contains(pt) or shp.touches(pt)
            except Exception:
                inside_match = False
            if inside_match:
                # return the original aircraft dict plus matched geo properties and DCA radial/range
                dca = _dca_radial_range(pt.y, pt.x)
                inside.append({"aircraft": a, "matched_props": props, "dca": dca})
                break
    return {"aircraft": inside}
