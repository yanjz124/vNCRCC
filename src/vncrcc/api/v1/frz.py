from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Any

from ... import storage
from ...geo.loader import find_geo_by_keyword, point_from_aircraft
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
    return {"radial_range": compact, "bearing": brng_i, "range_nm": round(dist_nm, 1)}

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
                dca = _dca_radial_range(pt.y, pt.x)
                history = storage.STORAGE.get_aircraft_position_history(a.get("cid"), 10) if storage.STORAGE else []
                inside.append({"aircraft": a, "matched_props": props, "dca": dca, "position_history": history})
                break
    return {"aircraft": inside}
