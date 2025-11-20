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
            # Ensure we still mark current inside with p56_buster flag
            current[str(cid)] = {
                "inside": True,
                "p56_buster": True,  # Ensure flag is set for continued tracking
                "outside_count": 0,  # Reset exit confirmation counter
                "last_seen": event_copy.get("latest_ts") or event_copy.get("recorded_at"),
                "last_position": event_copy.get("latest_position"),
                "flight_plan": event_copy.get("flight_plan", {}),
                "callsign": event_copy.get("callsign") or event_copy.get("flight_plan", {}).get("callsign"),
                "name": event_copy.get("name")
            }
            _atomic_write(data)
            return

    events.append(event_copy)

    # mark current inside with p56_buster flag for continuous tracking
    # store a small summary for the currently-inside pilot (include name/callsign)
    current[str(cid)] = {
        "inside": True,
        "p56_buster": True,  # Flag to enable continuous position tracking
        "outside_count": 0,  # Counter for exit confirmation (need 10 consecutive outside)
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
    """Update current_inside flags and track positions with p56_buster logic.

    P56 Buster Logic:
    - When intrusion detected: set p56_buster flag, start continuous position capture
    - Keep appending positions while aircraft is tracked (inside or within confirmation window)
    - Exit confirmation: need 10 consecutive 'outside' positions to stop tracking
    - Safety cap: 200 positions maximum per intrusion

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

    # For each tracked CID with p56_buster flag, update positions
    for cid, state in list(current.items()):
        p56_buster = state.get("p56_buster", False)
        if not p56_buster:
            # Not actively tracking this CID
            continue
        
        # Find the last event for this CID
        last_event = None
        for e in reversed(events):
            if str(e.get("cid")) == cid:
                last_event = e
                break
        
        if not last_event:
            # No event found, shouldn't happen but clean up
            current[cid]["p56_buster"] = False
            continue
        
        # Check if aircraft is currently inside P-56
        a = ac_map.get(str(cid))
        currently_inside = False
        if a:
            pt = point_from_aircraft(a)
            if pt:
                for shp, props in features:
                    try:
                        if getattr(shp, "contains", lambda x: False)(pt) or getattr(shp, "intersects", lambda x: False)(pt):
                            currently_inside = True
                            break
                    except Exception:
                        continue
        
        # Append current position to intrusion tracking
        # Get existing intrusion_positions or initialize empty list
        intrusion_positions = last_event.get("intrusion_positions", [])
        
        # Add current aircraft position if aircraft is still being tracked
        if a:
            pt = point_from_aircraft(a)
            if pt:
                # Create position entry from current aircraft data
                pos_entry = {
                    "ts": ts or time.time(),
                    "lat": pt.y,
                    "lon": pt.x,
                    "alt": a.get("altitude") or a.get("alt"),
                    "gs": a.get("groundspeed") or a.get("gs"),
                    "heading": a.get("heading"),
                    "callsign": a.get("callsign")
                }
                
                # Only append if different from last position (avoid duplicates from slow updates)
                if not intrusion_positions or intrusion_positions[-1]["ts"] < (ts or time.time()) - 1:
                    intrusion_positions.append(pos_entry)
                    
                    # Apply safety cap of 200 positions
                    if len(intrusion_positions) > 200:
                        intrusion_positions = intrusion_positions[-200:]
                    
                    # Update the event with captured positions
                    last_event["intrusion_positions"] = intrusion_positions
            
            # Update current_inside state
            if currently_inside:
                # Still inside - reset exit confirmation counter
                current[cid]["inside"] = True
                current[cid]["last_seen"] = ts or time.time()
                current[cid]["outside_count"] = 0
            else:
                # Outside - increment exit confirmation counter
                outside_count = state.get("outside_count", 0) + 1
                current[cid]["outside_count"] = outside_count
                current[cid]["inside"] = False
                current[cid]["last_seen"] = ts or time.time()
                
                # After 10 consecutive outside positions, stop tracking (confirmed exit)
                if outside_count >= 10:
                    current[cid]["p56_buster"] = False
                    last_event["exit_confirmed_at"] = ts or time.time()
                    # Split into inside and post-exit positions for display
                    if not last_event.get("exit_detected_at"):
                        # Mark first exit detection time (when counter started)
                        last_event["exit_detected_at"] = ts or time.time()
        elif not a:
            # Aircraft disconnected - stop tracking after 10 cycles
            outside_count = state.get("outside_count", 0) + 1
            current[cid]["outside_count"] = outside_count
            if outside_count >= 10:
                current[cid]["p56_buster"] = False
                if last_event and not last_event.get("exit_confirmed_at"):
                    last_event["exit_confirmed_at"] = ts or time.time()
        
        # Update post_positions for frontend display compatibility
        # Frontend expects pre_positions + post_positions for the yellow track
        if last_event and "intrusion_positions" in last_event:
            last_event["post_positions"] = last_event["intrusion_positions"]

    _atomic_write(data)
