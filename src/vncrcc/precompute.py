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
    """Compute which aircraft are inside a geofence using spatial indexing.

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

    # Build spatial index (STRtree) for O(log n) lookups instead of O(n)
    # Only create index if we have multiple shapes or many aircraft (worth the overhead)
    try:
        from shapely.strtree import STRtree
        if len(shapes) > 1 or len(aircraft) > 50:
            shape_geoms = [shp for shp, _ in shapes]
            tree = STRtree(shape_geoms)
        else:
            tree = None
    except Exception:
        tree = None

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

        # Use spatial index if available
        if tree:
            try:
                candidates = tree.query(pt)
                for candidate_shp in candidates:
                    if candidate_shp.contains(pt) or candidate_shp.touches(pt):
                        # Find matching props for this shape
                        for shp, props in shapes:
                            if shp == candidate_shp:
                                dca = _dca_radial_range(pt.y, pt.x)
                                inside.append({"aircraft": a, "matched_props": props, "dca": dca})
                                break
                        break
            except Exception:
                pass  # Fallback to linear search
        else:
            # Linear search fallback for small datasets
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


def _detect_p56_intrusions(data: Dict[str, Any], ts: float) -> List[Dict[str, Any]]:
    """Detect P56 intrusions and record them using p56_history semantics.

    - Point-inside OR line-crossing between two consecutive snapshots
    - 60s dedupe window per CID
    - Continuous stay counts as one; re-entry within 60s merges
    - Track up to 10 pre-positions and 1 post-position

    Returns list of breach dicts for caching.
    """
    from .storage import STORAGE
    from shapely.geometry import LineString, Point
    from .p56_history import record_penetration, sync_snapshot
    import os

    shapes = find_geo_by_keyword("p56")
    if not shapes or not STORAGE:
        return []

    snaps = STORAGE.get_latest_snapshots(2)
    if len(snaps) < 2:
        return []

    latest = snaps[0]
    prev = snaps[1]
    latest_ts = latest.get("fetched_at")
    prev_ts = prev.get("fetched_at")

    latest_ac = (latest.get("data") or {}).get("pilots") or (latest.get("data") or {}).get("aircraft") or []
    prev_ac = (prev.get("data") or {}).get("pilots") or (prev.get("data") or {}).get("aircraft") or []

    # Fetch position history for all aircraft from aircraft_history.json
    positions_by_cid: Dict[str, List] = {}
    write_json_history = os.getenv("VNCRCC_WRITE_JSON_HISTORY", "0").strip() == "1"
    if write_json_history:
        try:
            from .aircraft_history import get_history_for_cid
            # Get position history for all aircraft in the current snapshot
            for ac in latest_ac:
                cid = str(ac.get("cid") or "")
                if cid:
                    positions = get_history_for_cid(cid)
                    if positions:
                        # Convert to the format expected by the rest of the code
                        # aircraft_history format: {lat, lon, alt, ts, callsign}
                        # Convert to: {ts, lat, lon, alt, gs, heading, callsign}
                        converted_positions = []
                        for p in positions:
                            converted_positions.append({
                                "ts": p.get("ts", 0),
                                "lat": p.get("lat"),
                                "lon": p.get("lon"),
                                "alt": p.get("alt"),
                                "gs": p.get("gs"),
                                "heading": p.get("heading"),
                                "callsign": p.get("callsign", "")
                            })
                        positions_by_cid[cid] = converted_positions
        except Exception as e:
            pass

    # previous position map (only <= FL180)
    prev_map: Dict[str, Any] = {}
    for a in prev_ac:
        ident = str(a.get("cid") or a.get("callsign") or "")
        if not ident:
            continue
        pt = point_from_aircraft(a)
        if not pt:
            continue
        alt = a.get("altitude") or a.get("alt")
        try:
            alt_val = float(alt) if alt is not None else None
        except Exception:
            alt_val = None
        if alt_val is None or alt_val > 17999:
            continue
        prev_map[ident] = {"pos": (pt.x, pt.y)}

    breaches: List[Dict[str, Any]] = []
    for a in latest_ac:
        ident = str(a.get("cid") or a.get("callsign") or "")
        if not ident:
            continue
        latest_pt = point_from_aircraft(a)
        if not latest_pt:
            continue
        alt = a.get("altitude") or a.get("alt")
        try:
            alt_val = float(alt) if alt is not None else None
        except Exception:
            alt_val = None
        if alt_val is None or alt_val > 17999:
            continue

        matched_zones: List[str] = []
        line = None
        # line crossing between prev and latest
        if ident in prev_map:
            px, py = prev_map[ident]["pos"]
            line = LineString([(px, py), (latest_pt.x, latest_pt.y)])
            for shp, props in shapes:
                zone_name = props.get("name") or props.get("id") or "P-56"
                try:
                    if shp.intersects(line):
                        matched_zones.append(zone_name)
                except Exception:
                    continue

        # if not crossed, check connect-inside
        if not matched_zones:
            latest_inside = []
            for shp, props in shapes:
                zone_name = props.get("name") or props.get("id") or "P-56"
                try:
                    if shp.contains(latest_pt) or shp.intersects(latest_pt):
                        latest_inside.append(zone_name)
                except Exception:
                    continue
            if latest_inside:
                if ident in prev_map:
                    # verify not already inside previously
                    px, py = prev_map[ident]["pos"]
                    prev_inside = False
                    for shp, _ in shapes:
                        try:
                            if shp.contains(Point(px, py)):
                                prev_inside = True
                                break
                        except Exception:
                            continue
                    if not prev_inside:
                        matched_zones = latest_inside
                else:
                    # no previous point — treat as connect-inside
                    matched_zones = latest_inside

        if matched_zones:
            event = {
                "cid": a.get("cid"),
                "identifier": ident,
                "callsign": a.get("callsign"),
                "name": a.get("name"),
                "latest_position": {"lon": latest_pt.x, "lat": latest_pt.y},
                "latest_ts": latest_ts,
                "zones": matched_zones,
                "flight_plan": a.get("flight_plan", {}),
                "altitude": a.get("altitude"),
                "groundspeed": a.get("groundspeed"),
                "heading": a.get("heading"),
            }
            
            # Add pre_positions (up to 7 positions before the intrusion for better approach visualization)
            cid = str(a.get("cid") or "")
            if cid and cid in positions_by_cid:
                positions = positions_by_cid[cid]
                # Get positions before the intrusion timestamp
                pre_positions = [p for p in positions if p["ts"] < latest_ts]
                pre_positions.sort(key=lambda x: x["ts"], reverse=True)  # newest first
                pre_positions = pre_positions[:7]  # Keep last 7 for better context
                pre_positions.reverse()  # oldest first for display
                if pre_positions:
                    event["pre_positions"] = pre_positions
            
            try:
                record_penetration(event)
            except Exception:
                pass

            breaches.append(
                {
                    "identifier": ident,
                    "callsign": a.get("callsign"),
                    "cid": a.get("cid"),
                    "latest_position": {"lon": latest_pt.x, "lat": latest_pt.y},
                    "latest_ts": latest_ts,
                    "zones": matched_zones,
                }
            )

    # Update current_inside vs exits, passing position history for post_positions
    try:
        sync_snapshot(latest_ac, shapes, latest_ts, positions_by_cid=positions_by_cid if write_json_history else None)
    except Exception:
        pass

    return breaches


def precompute_all(data: Dict[str, Any], ts: float) -> None:
    """Pre-compute all expensive operations after a VATSIM fetch.

    This runs synchronously in the fetch callback, so keep it fast.
    If computation takes >1s, consider offloading to a thread pool.
    
    EVENT SURGE MODE: Automatically reduces radius when aircraft count is high
    to keep processing time reasonable on resource-constrained hardware.
    """
    try:
        start = datetime.now()
        
        # Extract VATSIM's update timestamp to measure processing delay
        vatsim_update_ts = None
        try:
            general = data.get("general", {})
            update_str = general.get("update_timestamp") or general.get("update")
            if update_str:
                from datetime import datetime as dt
                if 'T' in update_str or '-' in update_str:
                    vatsim_dt = dt.fromisoformat(update_str.replace('Z', '+00:00'))
                else:
                    y, m, d, h, mi, s = update_str[:4], update_str[4:6], update_str[6:8], update_str[8:10], update_str[10:12], update_str[12:14]
                    vatsim_dt = dt.strptime(f"{y}-{m}-{d}T{h}:{mi}:{s}Z", "%Y-%m-%dT%H:%M:%SZ")
                vatsim_update_ts = vatsim_dt.timestamp()
                delay_from_vatsim = ts - vatsim_update_ts
                logger.info(f"[TIMING] Precompute started {delay_from_vatsim:.1f}s after VATSIM update")
        except Exception:
            pass
        
        aircraft = data.get("pilots") or data.get("aircraft") or []
        total_aircraft = len(aircraft)
        
        # Dynamic radius adjustment for event surge protection
        # When VATSIM has 500+ aircraft, reduce processing load by focusing on core area
        effective_radius = _TRIM_RADIUS_NM
        if total_aircraft > 500:
            effective_radius = min(_TRIM_RADIUS_NM, 80)  # Reduce to 80nm during mega events
            logger.warning(f"EVENT SURGE: {total_aircraft} aircraft detected, reducing radius to {effective_radius}nm")
        elif total_aircraft > 300:
            effective_radius = min(_TRIM_RADIUS_NM, 150)  # Reduce to 150nm during large events
            logger.info(f"High traffic detected: {total_aircraft} aircraft, reducing radius to {effective_radius}nm")
        
        # Trim dataset to within configured radius of DCA to minimize processing
        if aircraft and effective_radius and effective_radius > 0:
            trimmed: List[Dict[str, Any]] = []
            for a in aircraft:
                try:
                    lat = a.get("latitude") or a.get("lat") or a.get("y")
                    lon = a.get("longitude") or a.get("lon") or a.get("x")
                    if lat is None or lon is None:
                        continue
                    d = _dca_radial_range(float(lat), float(lon))
                    if d.get("range_nm", 1e9) <= effective_radius:
                        trimmed.append(a)
                except Exception:
                    continue
            aircraft = trimmed
        count = len(aircraft)
        
        # Store surge mode status in cache for /api/status endpoint
        _CACHE["system_status"] = {
            "total_aircraft_vatsim": total_aircraft,
            "processed_aircraft": count,
            "configured_radius_nm": _TRIM_RADIUS_NM,
            "effective_radius_nm": effective_radius,
            "surge_mode": effective_radius < _TRIM_RADIUS_NM,
            "computed_at": ts
        }

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

        # Compute P-56 violations with intrusion detection and database logging
        # This uses line-crossing detection (requires 2 snapshots) and logs to incidents table
        p56_results = _detect_p56_intrusions(data, ts)
        _CACHE["p56"] = {
            "aircraft": p56_results,
            "computed_at": ts,
            "aircraft_count": count
        }

        # Extract VATSIM's update timestamp from the general section
        vatsim_update_timestamp = None
        try:
            general = data.get("general", {})
            vatsim_update_timestamp = general.get("update_timestamp") or general.get("update")
        except Exception:
            pass
        
        # Cache the trimmed aircraft list for fast /aircraft/list endpoint
        _CACHE["aircraft_list"] = {
            "aircraft": aircraft,
            "computed_at": ts,
            "total_count": count,
            "trim_radius_nm": _TRIM_RADIUS_NM,
            "vatsim_update_timestamp": vatsim_update_timestamp
        }

        elapsed = (datetime.now() - start).total_seconds()
        
        # Log timing breakdown with VATSIM delay if available
        timing_msg = (
            f"Pre-computed geofences in {elapsed:.3f}s: "
            f"SFRA={len(sfra_results)} FRZ={len(frz_results)} P56={len(p56_results)} "
            f"(processed aircraft={count}, radius_nm={_TRIM_RADIUS_NM})"
        )
        if vatsim_update_ts:
            total_delay = ts - vatsim_update_ts
            logger.info(f"[TIMING] {timing_msg} | Total delay from VATSIM: {total_delay:.1f}s")
        else:
            logger.info(timing_msg)

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
