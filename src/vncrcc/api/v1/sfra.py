from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Any

from ... import storage
from ...geo.loader import load_all_geojson, find_geo_by_keyword, point_from_aircraft
from ...precompute import get_cached
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

router = APIRouter(prefix="/sfra")


@router.get("/")
async def sfra_aircraft(name: str = Query("sfra", description="keyword to find the SFRA geojson file, default 'sfra'")) -> Dict[str, Any]:
    print("SFRA / endpoint called")
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
            print(f"SFRA: skipping {cid} - no point_from_aircraft result")
            continue
        # altitude: require present and <= 18000 ft
        alt = a.get("altitude") or a.get("alt")
        try:
            alt_val = float(alt) if alt is not None else None
        except Exception:
            alt_val = None
        # SFRA applies up to 17,999 ft; skip unknown altitude or above 17,999
        if alt_val is None or alt_val > 17999:
            print(f"SFRA: skipping {cid} - altitude filtered (alt={alt_val})")
            continue
        for shp, props in shapes:
            # treat points on the polygon boundary as inside as well
            try:
                inside_match = shp.contains(pt) or shp.touches(pt)
            except Exception:
                inside_match = False
            print(f"SFRA: processed {cid} - inside_match={inside_match}")
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
                        print(f"SFRA: vicinity aircraft {cid} at distance {dist_deg} deg (~{dist_deg*60:.2f} nm)")
                except Exception as e:
                    print(f"SFRA: vicinity check error for {cid}: {e}")
    return {"aircraft": inside}
