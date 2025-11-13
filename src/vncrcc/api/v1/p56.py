from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Any, Optional
from shapely.geometry import LineString
import json
import time

from ... import storage
from ...geo.loader import find_geo_by_keyword, point_from_aircraft
from ...p56_history import get_history, record_penetration, sync_snapshot

router = APIRouter(prefix="/p56")


def _identifier(a: dict) -> Optional[str]:
    # prefer cid if present, otherwise callsign
    cid = a.get("cid")
    if cid:
        return str(cid)
    cs = a.get("callsign") or a.get("call_sign")
    if cs:
        return str(cs).strip()
    return None


@router.get("/")
async def p56_breaches(name: str = Query("p56", description="keyword to find the P56 geojson file, default 'p56'")) -> Dict[str, Any]:
    shapes = find_geo_by_keyword(name)
    if not shapes:
        raise HTTPException(status_code=404, detail=f"No geo named like '{name}' found in geo directory")
    # For penetration calculation we require at least two snapshots
    snaps = storage.STORAGE.get_latest_snapshots(2) if storage.STORAGE else []
    if len(snaps) < 2:
        return {"breaches": [], "note": "need 2 snapshots to calculate P56 penetration", "history": get_history()}
    latest = snaps[0]
    prev = snaps[1]
    latest_ts = latest.get("fetched_at")
    prev_ts = prev.get("fetched_at")

    latest_ac = (latest.get("data") or {}).get("pilots") or (latest.get("data") or {}).get("aircraft") or []
    prev_ac = (prev.get("data") or {}).get("pilots") or (prev.get("data") or {}).get("aircraft") or []

    prev_map = {}
    for a in prev_ac:
        ident = _identifier(a)
        if not ident:
            continue
        pt = point_from_aircraft(a)
        if not pt:
            continue
        # only consider previous positions within the vertical limit (<= 17,999 ft)
        alt_prev = a.get("altitude") or a.get("alt")
        try:
            alt_prev_val = float(alt_prev) if alt_prev is not None else None
        except Exception:
            alt_prev_val = None
        if alt_prev_val is None or alt_prev_val > 17999:
            continue
        prev_map[ident] = {"pos": (pt.x, pt.y), "raw": a}

    breaches: List[Dict[str, Any]] = []
    # shapes is a list of (shape, properties) tuples; check all features
    features = shapes
    for a in latest_ac:
        ident = _identifier(a)
        if not ident:
            continue
        latest_pt = point_from_aircraft(a)
        if not latest_pt:
            continue
        # only consider latest positions within the vertical limit (<= 17,999 ft)
        alt_latest = a.get("altitude") or a.get("alt")
        try:
            alt_latest_val = float(alt_latest) if alt_latest is not None else None
        except Exception:
            alt_latest_val = None
        if alt_latest_val is None or alt_latest_val > 17999:
            continue

        # Check line intersection if we have a previous position for this ident
        matched_zones = []
        line = None
        if ident in prev_map:
            prev_pos = prev_map[ident]["pos"]
            line = LineString([(prev_pos[0], prev_pos[1]), (latest_pt.x, latest_pt.y)])
            for idx, (shp, props) in enumerate(features):
                zone_name = props.get("name") or props.get("id") or f"{name}:{idx}"
                try:
                    if shp.intersects(line):
                        matched_zones.append(zone_name)
                except Exception:
                    continue

        if not matched_zones:
            # no penetration detected for this aircraft
            continue
        prev_pos = prev_map[ident]["pos"] if ident in prev_map else None
        evidence = {
            "zones": matched_zones,
            "line": list(line.coords) if line is not None else None,
            "prev_ts": prev_ts,
            "latest_ts": latest_ts,
            "flight_plan": a.get("flight_plan", {}),
            "name": a.get("name"),
            "callsign": a.get("callsign"),
        }

        # persist incident to storage
        detected_at = latest_ts or time.time()
        try:
            if storage and getattr(storage, "STORAGE", None):
                storage.STORAGE.save_incident(
                    detected_at=detected_at,
                    callsign=a.get("callsign") or "",
                    cid=a.get("cid"),
                    lat=float(latest_pt.y),
                    lon=float(latest_pt.x),
                    altitude=a.get("altitude") or a.get("alt"),
                    zone=",".join(matched_zones) or name,
                    evidence=json.dumps(evidence),
                )
        except Exception:
            # don't let storage failures stop detection; continue
            pass

        # record penetration in history
        record_penetration({
            "cid": a.get("cid"),
            "identifier": ident,
            "callsign": a.get("callsign"),
            "name": a.get("name"),
            "latest_position": {"lon": latest_pt.x, "lat": latest_pt.y},
            "latest_ts": latest_ts,
            "zones": matched_zones,
            "flight_plan": a.get("flight_plan", {}),
        })

        breaches.append(
            {
                "identifier": ident,
                "callsign": a.get("callsign"),
                "cid": a.get("cid"),
                "prev_position": {"lon": prev_pos[0], "lat": prev_pos[1]} if prev_pos is not None else None,
                "latest_position": {"lon": latest_pt.x, "lat": latest_pt.y},
                "prev_ts": prev_ts if prev_pos is not None else None,
                "latest_ts": latest_ts,
                "zones": matched_zones,
                "evidence": evidence,
                "flight_plan": a.get("flight_plan", {}),
            }
        )
    # sync history with current snapshot to mark exits
    sync_snapshot(latest_ac, features, latest_ts)
    return {"breaches": breaches, "history": get_history()}
