import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .geo.loader import point_from_aircraft

HISTORY_PATH = Path.cwd() / "data" / "p56_history.json"
# If two intrusions for the same CID occur within this many seconds, treat as one
DEDUPE_WINDOW_SECONDS = 60


def _ensure_parent():
    # Accept either a pathlib.Path or a string (tests set a string path).
    p = HISTORY_PATH if isinstance(HISTORY_PATH, Path) else Path(HISTORY_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)


def _load() -> Dict[str, Any]:
    _ensure_parent()
    p = HISTORY_PATH if isinstance(HISTORY_PATH, Path) else Path(HISTORY_PATH)
    if not p.exists():
        return {"events": [], "current_inside": {}}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {"events": [], "current_inside": {}}


def _atomic_write(data: Dict[str, Any]):
    _ensure_parent()
    p = HISTORY_PATH if isinstance(HISTORY_PATH, Path) else Path(HISTORY_PATH)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, default=str))
    tmp.replace(p)


def get_history() -> Dict[str, Any]:
    return _load()


def clear_history() -> None:
    """Clear all recorded P-56 events and current_inside state.

    This overwrites the history file with an empty structure. Use with
    caution — this is irreversible.
    """
    _atomic_write({"events": [], "current_inside": {}})


def purge_events(keys: Optional[List[str]] = None, items: Optional[List[Dict[str, Any]]] = None) -> Dict[str, int]:
    """Remove selected events from history by keys or explicit items.

    A key is a string formatted as "<cid>:<recorded_at>" where recorded_at
    is the exact float timestamp used when the event was written. Alternatively,
    callers may provide items as a list of {"cid": ..., "recorded_at": ...}.

    Returns a dict with counts: {"before": N, "after": M, "purged": (N-M)}.
    """
    data = _load()
    events: List[Dict[str, Any]] = data.setdefault("events", [])
    before = len(events)

    # Build a set of (cid_str, recorded_at_str) tuples to remove for fast lookup
    targets = set()
    if items:
        for it in items:
            try:
                cid = str(it.get("cid") or "")
                ra = it.get("recorded_at")
                if ra is None:
                    continue
                ra_s = str(ra)
                targets.add((cid, ra_s))
            except Exception:
                continue
    if keys:
        for k in keys:
            try:
                cid_s, ra_s = str(k).split(":", 1)
                targets.add((cid_s, ra_s))
            except Exception:
                continue

    if not targets:
        return {"before": before, "after": before, "purged": 0}

    kept: List[Dict[str, Any]] = []
    for e in events:
        try:
            cid_s = str(e.get("cid") or "")
            ra_s = str(e.get("recorded_at")) if (e.get("recorded_at") is not None) else ""
            if (cid_s, ra_s) in targets:
                continue  # purge this one
            kept.append(e)
        except Exception:
            # if malformed, keep to avoid accidental deletion
            kept.append(e)

    data["events"] = kept
    _atomic_write(data)
    after = len(kept)
    return {"before": before, "after": after, "purged": max(0, before - after)}


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

    # Append event with recorded_at timestamp, unless a recent event exists
    event_copy = dict(event)
    event_copy.setdefault("recorded_at", time.time())

    # Deduplicate: if the last recorded event for this CID is within the
    # DEDUPE_WINDOW_SECONDS, merge the new data into that event instead of
    # appending a new one so quick re-entries count as a single buster.
    last_event = None
    for e in reversed(events):
        if str(e.get("cid")) == str(cid):
            last_event = e
            break

    if last_event:
        try:
            last_ts = float(last_event.get("recorded_at") or 0)
        except Exception:
            last_ts = 0
        if (event_copy.get("recorded_at", 0) - last_ts) <= DEDUPE_WINDOW_SECONDS:
            # Merge useful fields from the incoming event into last_event.
            # Preserve the original recorded_at (earliest detection).
            # Update latest_ts if provided and is newer.
            new_ts = event_copy.get("latest_ts")
            if new_ts is not None:
                prev_ts = last_event.get("latest_ts")
                new_ts_f = None
                prev_ts_f = None
                try:
                    new_ts_f = float(new_ts)
                except Exception:
                    new_ts_f = None
                try:
                    if prev_ts is not None:
                        prev_ts_f = float(prev_ts)
                except Exception:
                    prev_ts_f = None
                if prev_ts_f is None or (new_ts_f is not None and new_ts_f > prev_ts_f):
                    last_event["latest_ts"] = new_ts
            # Merge pre_positions/post_positions if available and last_event doesn't have them
            if event_copy.get("pre_positions") and not last_event.get("pre_positions"):
                last_event["pre_positions"] = event_copy.get("pre_positions")
            if event_copy.get("post_positions") and not last_event.get("post_positions"):
                last_event["post_positions"] = event_copy.get("post_positions")
            # Ensure we still mark current inside
            current[str(cid)] = {
                "inside": True,
                "last_seen": event_copy.get("latest_ts") or event_copy.get("recorded_at"),
                "last_position": event_copy.get("latest_position"),
                "flight_plan": event_copy.get("flight_plan", {}),
                "callsign": event_copy.get("callsign") or event_copy.get("flight_plan", {}).get("callsign"),
                "name": event_copy.get("name")
            }
            _atomic_write(data)
            return

    events.append(event_copy)

    # mark current inside
    # store a small summary for the currently-inside pilot (include name/callsign)
    current[str(cid)] = {
        "inside": True,
        "last_seen": event_copy.get("latest_ts") or event_copy.get("recorded_at"),
        "last_position": event_copy.get("latest_position"),
        "flight_plan": event_copy.get("flight_plan", {}),
        "callsign": event_copy.get("callsign") or event_copy.get("flight_plan", {}).get("callsign"),
        "name": event_copy.get("name")
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

    # For each tracked CID (inside or recently exited), check status and update positions
    for cid, state in list(current.items()):
        is_inside = state.get("inside", False)
        last_seen = state.get("last_seen", 0)
        
        # Skip if exited more than 2 minutes ago (enough time for 5+ positions after exit)
        if not is_inside and ts and (ts - last_seen > 120):
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
        
        # Find the last event for this CID
        last_event = None
        for e in reversed(events):
            if str(e.get("cid")) == cid:
                last_event = e
                break
        
        # Get the last event for this CID to update positions (whether inside or recently exited)
        if last_event and positions_by_cid:
            entry_ts = last_event.get("latest_ts", 0)
            
            if entry_ts:
                positions = positions_by_cid.get(cid, [])
                # Get all positions after entry
                post_entry = [p for p in positions if p["ts"] > entry_ts]
                post_entry.sort(key=lambda x: x["ts"])  # oldest first
                
                if still_inside and is_inside:
                    # Still inside - update with all inside positions (cap at 100 for safety)
                    last_event["post_positions"] = post_entry[:100]
                elif not still_inside:
                    # Exited or still tracking after exit
                    if is_inside:
                        # First detection of exit - mark it
                        current[cid]["inside"] = False
                        current[cid]["last_seen"] = ts or time.time()
                        last_event["exit_detected_at"] = ts or time.time()
                    
                    # Continue tracking positions after exit
                    split_ts = last_event.get("exit_detected_at", ts or time.time())
                    inside_positions = [p for p in post_entry if p["ts"] <= split_ts]
                    after_exit = [p for p in post_entry if p["ts"] > split_ts]
                    
                    # Combine: all inside (cap at 100) + up to 5 after exit
                    final_positions = inside_positions[:100] + after_exit[:5]
                    last_event["post_positions"] = final_positions

    _atomic_write(data)
