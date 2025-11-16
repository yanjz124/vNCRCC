"""Pre-computation engine for VATSIM data.

This module runs expensive calculations (geofence checks, analytics) immediately
after each VATSIM fetch, storing results in memory. API endpoints then return
pre-computed results instantly instead of doing computation per-request.

Design:
- Runs as a callback registered with the VatsimClient
- Computes all geofence violations (SFRA/FRZ/P-56) once per fetch
- Stores results in a simple in-memory cache
- API endpoints check cache first before falling back to live computation
"""

import logging
import os
from typing import Any, Dict, List, Optional
from datetime import datetime
import math

from .geo.loader import find_geo_by_keyword, point_from_aircraft

logger = logging.getLogger("vncrcc.precompute")

# In-memory cache of pre-computed results
# Structure: {"sfra": {...}, "frz": {...}, "p56": {...}, ...}
_CACHE: Dict[str, Any] = {}

# DCA bullseye (lat, lon) for radial/range calculations
DCA_BULL = (38.8514403, -77.0377214)

# Optional server-side radius trim around DCA to reduce processing load.
# Set env VNCRCC_TRIM_RADIUS_NM to a number (e.g., 300) to enable.
try:
    _TRIM_RADIUS_NM = float(os.environ.get("VNCRCC_TRIM_RADIUS_NM", "300"))
except Exception:
    _TRIM_RADIUS_NM = 300.0


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


def _compute_geofence(aircraft: List[Dict[str, Any]], geo_keyword: str, max_altitude: Optional[float] = None) -> List[Dict[str, Any]]:
    """Compute which aircraft are inside a geofence.

    Args:
        aircraft: List of aircraft dicts from VATSIM data
        geo_keyword: Keyword to find geojson (e.g., "sfra", "frz", "p56")
        max_altitude: If set, filter out aircraft above this altitude (ft)

    Returns:
        List of matches with {"aircraft": {...}, "matched_props": {...}, "dca": {...}}
    """
    shapes = find_geo_by_keyword(geo_keyword)
    if not shapes:
        logger.warning(f"No geo shapes found for keyword '{geo_keyword}'")
        return []

    inside: List[Dict[str, Any]] = []
    for a in aircraft:
        cid = a.get("cid") or a.get("callsign") or '<no-cid>'
        pt = point_from_aircraft(a)
        if not pt:
            continue

        # altitude filter
        if max_altitude is not None:
            alt = a.get("altitude") or a.get("alt")
            try:
                alt_val = float(alt) if alt is not None else None
            except Exception:
                alt_val = None
            if alt_val is None or alt_val > max_altitude:
                continue

        for shp, props in shapes:
            try:
                inside_match = shp.contains(pt) or shp.touches(pt)
            except Exception:
                inside_match = False

            if inside_match:
                dca = _dca_radial_range(pt.y, pt.x)
                inside.append({"aircraft": a, "matched_props": props, "dca": dca})
                break

    return inside


def precompute_all(data: Dict[str, Any], ts: float) -> None:
    """Pre-compute all expensive operations after a VATSIM fetch.

    This runs synchronously in the fetch callback, so keep it fast.
    If computation takes >1s, consider offloading to a thread pool.
    """
    try:
        start = datetime.now()
        aircraft = data.get("pilots") or data.get("aircraft") or []
        # Trim dataset to within configured radius of DCA to minimize processing
        if aircraft and _TRIM_RADIUS_NM and _TRIM_RADIUS_NM > 0:
            trimmed: List[Dict[str, Any]] = []
            for a in aircraft:
                try:
                    lat = a.get("latitude") or a.get("lat") or a.get("y")
                    lon = a.get("longitude") or a.get("lon") or a.get("x")
                    if lat is None or lon is None:
                        continue
                    d = _dca_radial_range(float(lat), float(lon))
                    if d.get("range_nm", 1e9) <= _TRIM_RADIUS_NM:
                        trimmed.append(a)
                except Exception:
                    continue
            aircraft = trimmed
        count = len(aircraft)

        # Compute SFRA violations (altitude <= 17999 ft)
        sfra_results = _compute_geofence(aircraft, "sfra", max_altitude=17999)
        _CACHE["sfra"] = {
            "aircraft": sfra_results,
            "computed_at": ts,
            "aircraft_count": count
        }

        # Compute FRZ violations (altitude <= 17999 ft)
        frz_results = _compute_geofence(aircraft, "frz", max_altitude=17999)
        _CACHE["frz"] = {
            "aircraft": frz_results,
            "computed_at": ts,
            "aircraft_count": count
        }

        # Compute P-56 violations (no altitude limit for P-56)
        p56_results = _compute_geofence(aircraft, "p56", max_altitude=None)
        _CACHE["p56"] = {
            "aircraft": p56_results,
            "computed_at": ts,
            "aircraft_count": count
        }

        elapsed = (datetime.now() - start).total_seconds()
        logger.info(
            f"Pre-computed geofences in {elapsed:.3f}s: "
            f"SFRA={len(sfra_results)} FRZ={len(frz_results)} P56={len(p56_results)} "
            f"(processed aircraft={count}, radius_nm={_TRIM_RADIUS_NM})"
        )

    except Exception as e:
        logger.exception(f"Pre-computation error: {e}")


def get_cached(key: str) -> Optional[Dict[str, Any]]:
    """Get pre-computed result by key (e.g., 'sfra', 'frz', 'p56').

    Returns None if no cached data available.
    """
    return _CACHE.get(key)


def clear_cache() -> None:
    """Clear all cached pre-computed results."""
    _CACHE.clear()


__all__ = ["precompute_all", "get_cached", "clear_cache"]
