import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .geo.loader import point_from_aircraft

HISTORY_PATH = Path.cwd() / "data" / "p56_history.json"


def _ensure_parent():
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)


def _load() -> Dict[str, Any]:
    _ensure_parent()
    if not HISTORY_PATH.exists():
        return {"events": [], "current_inside": {}}
    try:
        return json.loads(HISTORY_PATH.read_text())
    except Exception:
        return {"events": [], "current_inside": {}}


def _atomic_write(data: Dict[str, Any]):
    _ensure_parent()
    tmp = HISTORY_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, default=str))
    tmp.replace(HISTORY_PATH)


def get_history() -> Dict[str, Any]:
    return _load()


def record_penetration(event: Dict[str, Any]) -> None:
    """Record a new penetration event. Event should include at least 'cid' or 'identifier'."""
    data = _load()
    events: List[Dict[str, Any]] = data.setdefault("events", [])
    current: Dict[str, Any] = data.setdefault("current_inside", {})

    cid = event.get("cid") or event.get("identifier")
    if not cid:
        # fallback: generate an identifier using callsign+timestamp
        cid = f"NOCID-{int(time.time())}"
        event["cid"] = cid

    # If already marked inside, don't double-record
    state = current.get(str(cid))
    if state and state.get("inside"):
        # already inside; ignore duplicate penetration
        return

    # Append event with recorded_at timestamp
    event_copy = dict(event)
    event_copy.setdefault("recorded_at", time.time())
    events.append(event_copy)

    # mark current inside
    current[str(cid)] = {
        "inside": True,
        "last_seen": event_copy.get("latest_ts") or event_copy.get("recorded_at"),
        "last_position": event_copy.get("latest_position"),
        "flight_plan": event_copy.get("flight_plan", {}),
    }

    _atomic_write(data)


def mark_exit(cid: str, ts: Optional[float] = None) -> None:
    data = _load()
    current: Dict[str, Any] = data.setdefault("current_inside", {})
    if str(cid) in current:
        current[str(cid)]["inside"] = False
        current[str(cid)]["last_seen"] = ts or time.time()
        _atomic_write(data)


def sync_snapshot(aircraft_list: List[Dict[str, Any]], features: List, ts: Optional[float] = None, positions_by_cid: Optional[Dict[str, List]] = None) -> None:
    """Update current_inside flags based on latest snapshot.

    aircraft_list: list of VATSIM aircraft dicts
    features: list of (shapely_shape, props)
    positions_by_cid: dict of cid to list of position dicts
    """
    data = _load()
    current: Dict[str, Any] = data.setdefault("current_inside", {})
    events: List[Dict[str, Any]] = data.setdefault("events", [])
    # Build map by cid
    ac_map: Dict[str, Dict[str, Any]] = {}
    for a in aircraft_list:
        cid = a.get("cid")
        if cid:
            ac_map[str(cid)] = a

    # For each currently inside CID, check if still inside
    for cid, state in list(current.items()):
        if not state.get("inside"):
            continue
        a = ac_map.get(str(cid))
        still_inside = False
        if a:
            pt = point_from_aircraft(a)
            if pt:
                for shp, props in features:
                    try:
                        if getattr(shp, "contains", lambda x: False)(pt) or getattr(shp, "intersects", lambda x: False)(pt):
                            still_inside = True
                            break
                    except Exception:
                        continue
        if not still_inside:
            # mark exit
            current[cid]["inside"] = False
            current[cid]["last_seen"] = ts or time.time()
            # add post_positions to the last event for this cid
            last_event = None
            for e in reversed(events):
                if str(e.get("cid")) == cid:
                    last_event = e
                    break
            if last_event and positions_by_cid:
                latest_ts = last_event.get("latest_ts")
                if latest_ts:
                    positions = positions_by_cid.get(cid, [])
                    post_positions = [p for p in positions if p["ts"] > latest_ts]
                    post_positions.sort(key=lambda x: x["ts"])  # oldest first
                    post_positions = post_positions[:5]
                    last_event.setdefault("post_positions", post_positions)

    _atomic_write(data)
