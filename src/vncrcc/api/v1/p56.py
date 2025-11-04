from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Any, Optional
from shapely.geometry import LineString
import json
import time

from ... import storage
from ...geo.loader import find_geo_by_keyword, point_from_aircraft

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
        return {"breaches": [], "note": "need 2 snapshots to calculate P56 penetration"}
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
        prev_map[ident] = {"pos": (pt.x, pt.y), "raw": a}

    breaches: List[Dict[str, Any]] = []
    pshape = shapes[0][0]  # use first shape
    for a in latest_ac:
        ident = _identifier(a)
        if not ident:
            continue
        if ident not in prev_map:
            continue
        latest_pt = point_from_aircraft(a)
        if not latest_pt:
            continue
        prev_pos = prev_map[ident]["pos"]
        line = LineString([(prev_pos[0], prev_pos[1]), (latest_pt.x, latest_pt.y)])
        # If the line intersects the P56 polygon, we consider that a penetration
        if pshape.intersects(line) or pshape.contains(latest_pt):
            evidence = {
                "line": list(line.coords),
                "prev_ts": prev_ts,
                "latest_ts": latest_ts,
            }
            # persist incident to storage
            detected_at = latest_ts or time.time()
            try:
                STORAGE.save_incident(
                    detected_at=detected_at,
                    callsign=a.get("callsign") or "",
                    cid=a.get("cid"),
                    lat=float(latest_pt.y),
                    lon=float(latest_pt.x),
                    altitude=a.get("altitude") or a.get("alt"),
                    zone=name,
                    evidence=json.dumps(evidence),
                )
            except Exception:
                # don't let storage failures stop detection; continue
                pass

            breaches.append(
                {
                    "identifier": ident,
                    "callsign": a.get("callsign"),
                    "cid": a.get("cid"),
                    "prev_position": {"lon": prev_pos[0], "lat": prev_pos[1]},
                    "latest_position": {"lon": latest_pt.x, "lat": latest_pt.y},
                    "prev_ts": prev_ts,
                    "latest_ts": latest_ts,
                    "evidence_line": list(line.coords),
                }
            )
    return {"breaches": breaches}
