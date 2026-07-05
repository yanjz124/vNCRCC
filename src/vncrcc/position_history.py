"""In-memory rolling position history per aircraft (CID).

Purpose: provide the pre-intrusion "approach" track for P-56 events without
depending on the optional JSON history file (VNCRCC_WRITE_JSON_HISTORY) or on
disk I/O. Intrusion/post positions are captured from live snapshots regardless,
but pre_positions previously required the JSON history to be enabled — so with
the flag off, events showed intrusion/post but no approach path.

This tracker is updated every precompute cycle for all aircraft, so by the time
an aircraft crosses into P-56 its recent approach fixes are already in memory.
Memory is bounded: a short ring buffer per CID, pruned to currently-active CIDs
each cycle.
"""
from collections import deque
from typing import Any, Deque, Dict, List

# Keep a handful of recent fixes per aircraft — enough to draw the approach
# leading up to a zone entry without growing unbounded.
_MAX_FIXES = 12

# cid (str) -> deque of position dicts (oldest -> newest)
_POSITIONS: Dict[str, Deque[Dict[str, Any]]] = {}


def _coords(a: Dict[str, Any]):
    lat = a.get("latitude") or a.get("lat") or a.get("y")
    lon = a.get("longitude") or a.get("lon") or a.get("x")
    if lat is None or lon is None:
        return None
    try:
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None


def record_snapshot(aircraft_list: List[Dict[str, Any]], ts: float) -> None:
    """Append the current position of every aircraft to its ring buffer, and
    drop aircraft that are no longer present so memory stays bounded.

    Call this once per cycle AFTER computing pre_positions, so the tracker holds
    only prior-cycle fixes while an intrusion is being evaluated.
    """
    active: set = set()
    for a in aircraft_list:
        cid = str(a.get("cid") or "")
        if not cid:
            continue
        coords = _coords(a)
        if coords is None:
            continue
        active.add(cid)
        buf = _POSITIONS.get(cid)
        if buf is None:
            buf = deque(maxlen=_MAX_FIXES)
            _POSITIONS[cid] = buf
        lat, lon = coords
        buf.append({
            "ts": ts,
            "lat": lat,
            "lon": lon,
            "alt": a.get("altitude") or a.get("alt"),
            "gs": a.get("groundspeed") or a.get("gs"),
            "heading": a.get("heading"),
            "callsign": a.get("callsign"),
        })

    # Prune aircraft that disconnected / left the dataset this cycle.
    for cid in [c for c in _POSITIONS if c not in active]:
        del _POSITIONS[cid]


def get_pre_positions(cid: str, before_ts: float, limit: int = 7) -> List[Dict[str, Any]]:
    """Return up to `limit` recent fixes strictly before `before_ts`, oldest
    first — the approach path leading up to a zone entry."""
    buf = _POSITIONS.get(str(cid))
    if not buf:
        return []
    before = [dict(p) for p in buf if p.get("ts") is not None and p["ts"] < before_ts]
    before.sort(key=lambda x: x["ts"])  # oldest first
    if len(before) > limit:
        before = before[-limit:]
    return before


def clear() -> None:
    _POSITIONS.clear()
