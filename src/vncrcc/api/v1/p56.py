from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Any, Optional
import os
from fastapi import Body
from pathlib import Path


def _load_dotenv_if_present(max_levels: int = 6):
    """Lightweight .env loader: walk up from this file and, if a .env
    file is found, read key=value lines and set os.environ for keys that
    are not already set. This avoids adding a dependency like python-dotenv.
    """
    try:
        p = Path(__file__).resolve()
        for _ in range(max_levels):
            env_path = p / '.env'
            if env_path.exists():
                try:
                    for line in env_path.read_text(encoding='utf8').splitlines():
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        if '=' not in line:
                            continue
                        k, v = line.split('=', 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k and os.environ.get(k) is None:
                            os.environ[k] = v
                except Exception:
                    # best-effort only
                    pass
                return
            p = p.parent
    except Exception:
        pass


# Attempt to load a .env file (if present in the repo root or higher)
_load_dotenv_if_present()
from shapely.geometry import LineString
import json
import time

from ... import storage
from ...geo.loader import find_geo_by_keyword, point_from_aircraft
from ...p56_history import get_history, record_penetration, sync_snapshot
from ...aircraft_history import get_history as get_ac_history
from shapely.geometry import Point

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
    # Return pre-computed result if available (instant response for all users)
    from ...precompute import get_cached
    cached = get_cached("p56")
    if cached:
        # also include current p56 history
        return {"breaches": cached.get("aircraft", []), "history": get_history(), "fetched_at": cached.get("computed_at")}
    
    # Fallback to on-demand computation if cache not available
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
            # No line intersection detected. However, the aircraft may have
            # appeared (connected) already inside the P56 zone — detect that
            # by testing the latest point directly against the zones. If the
            # previous snapshot shows the aircraft was already inside, skip
            # (it's not a new penetration).
            latest_inside_zones = []
            for idx, (shp, props) in enumerate(features):
                zone_name = props.get("name") or props.get("id") or f"{name}:{idx}"
                try:
                    if getattr(shp, "contains", lambda x: False)(latest_pt) or getattr(shp, "intersects", lambda x: False)(latest_pt):
                        latest_inside_zones.append(zone_name)
                except Exception:
                    continue
            if latest_inside_zones:
                # Check whether previous position was also inside (if we have it)
                prev_inside = False
                if ident in prev_map:
                    try:
                        px, py = prev_map[ident]["pos"]
                        from shapely.geometry import Point as ShPoint
                        pprev = ShPoint(px, py)
                        for shp, props in features:
                            try:
                                if getattr(shp, "contains", lambda x: False)(pprev) or getattr(shp, "intersects", lambda x: False)(pprev):
                                    prev_inside = True
                                    break
                            except Exception:
                                continue
                    except Exception:
                        prev_inside = False
                if prev_inside:
                    # already inside in previous snapshot; not a new penetration
                    continue
                # treat as penetration (connect-inside)
                matched_zones = latest_inside_zones
            else:
                # still no zones matched, skip
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

        # Build pre_positions from cached aircraft history up to the first
        # position found outside the P56 zones (walk backwards from newest).
        pre_positions = []
        try:
            ac_hist = get_ac_history().get("history", {})
            # Prefer numeric CID key if available, otherwise use identifier
            hist_key = None
            if a.get("cid") is not None:
                hist_key = str(a.get("cid"))
            elif ident:
                hist_key = str(ident)
            positions = ac_hist.get(hist_key, []) if hist_key else []
            # Ensure positions are sorted oldest->newest by ts
            positions = sorted([p for p in positions if p.get("ts")], key=lambda x: x["ts"]) if positions else []
            # Walk backwards from newest until we encounter a point outside all zones
            for p in reversed(positions):
                try:
                    pt = Point(p.get("lon") or p.get("x") or 0, p.get("lat") or p.get("y") or 0)
                    inside_any = False
                    for shp, props in features:
                        try:
                            if getattr(shp, "contains", lambda x: False)(pt) or getattr(shp, "intersects", lambda x: False)(pt):
                                inside_any = True
                                break
                        except Exception:
                            continue
                    if not inside_any:
                        # stop at the first position outside
                        break
                    pre_positions.append({"lon": float(p.get("lon") or p.get("x")), "lat": float(p.get("lat") or p.get("y")), "ts": p.get("ts")})
                    # cap to last 10 to limit payload
                    if len(pre_positions) >= 10:
                        break
                except Exception:
                    continue
            # pre_positions currently collected newest->oldest, reverse to oldest->newest
            pre_positions = list(reversed(pre_positions))
        except Exception:
            pre_positions = []

        record_penetration({
            "cid": a.get("cid"),
            "identifier": ident,
            "callsign": a.get("callsign"),
            "name": a.get("name"),
            "latest_position": {"lon": latest_pt.x, "lat": latest_pt.y},
            "latest_ts": latest_ts,
            "zones": matched_zones,
            "flight_plan": a.get("flight_plan", {}),
            "pre_positions": pre_positions,
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
    # Build positions_by_cid mapping from aircraft_history to allow sync to
    # populate post_positions for events when aircraft exit.
    positions_by_cid = {}
    try:
        ac_hist = get_ac_history().get("history", {})
        for k, v in ac_hist.items():
            # normalize into list of {'lat','lon','ts'} sorted by ts
            pts = []
            for p in v:
                try:
                    pts.append({"lat": float(p.get("lat") or p.get("y")), "lon": float(p.get("lon") or p.get("x")), "ts": p.get("ts")})
                except Exception:
                    continue
            pts = sorted([pt for pt in pts if pt.get("ts") is not None], key=lambda x: x["ts"]) if pts else []
            positions_by_cid[str(k)] = pts
    except Exception:
        positions_by_cid = {}

    # sync history with current snapshot to mark exits
    sync_snapshot(latest_ac, features, latest_ts, positions_by_cid)
    return {"breaches": breaches, "history": get_history()}



@router.post("/clear")
async def p56_clear(payload: Dict[str, str] = Body(...)) -> Dict[str, Any]:
    """Clear P-56 history (events and current_inside).

    This endpoint requires the server admin password to be set in the
    VNCRCC_ADMIN_PASSWORD environment variable and provided in the POST
    body as JSON {"password": "..."}.
    """
    admin_pwd = os.getenv("VNCRCC_ADMIN_PASSWORD")
    if not admin_pwd:
        raise HTTPException(status_code=403, detail="Server admin password not configured")
    provided = payload.get("password")
    if not provided or provided != admin_pwd:
        raise HTTPException(status_code=403, detail="Invalid password")
    # perform clear
    try:
        from ...p56_history import clear_history
        clear_history()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear P56 history: {e}")
    return {"status": "ok", "cleared": True}
