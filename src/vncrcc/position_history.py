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
import os
from collections import deque
from typing import Any, Deque, Dict, List

from .geo_utils import haversine_nm, DCA_LAT, DCA_LON

# This tracker exists only to supply the approach path for P-56 events, and
# P-56 sits over downtown DC. The snapshot pushed into the buffer is the raw
# VATSIM feed -- the radius trim in precompute_all happens on a local copy and
# never reaches here -- so without a filter we were buffering every aircraft on
# the network (~1700) purely to serve a handful near DCA. That is what forced
# the buffer to stay tiny, which in turn capped the approach track at a couple
# of minutes.
#
# Filtering to a DCA radius instead lets the buffer be generous: only a
# handful of aircraft are ever in range, so a long history costs very little.
# An aircraft beyond this radius cannot reach P-56 within the buffer window
# anyway, and it re-enters the tracker as soon as it comes inside.
try:
    _RADIUS_NM = float(os.environ.get("VNCRCC_POSITION_HISTORY_RADIUS_NM", "150"))
except (TypeError, ValueError):
    _RADIUS_NM = 150.0

# At the ~11s effective cycle cadence this is roughly 45 minutes of approach
# track per aircraft -- far more than needed to render an intrusion, and cheap
# now that only in-range aircraft are held.
try:
    _MAX_FIXES = int(os.environ.get("VNCRCC_POSITION_HISTORY_FIXES", "240"))
except (TypeError, ValueError):
    _MAX_FIXES = 240

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


def in_range(lat: float, lon: float) -> bool:
    """True if a position is close enough to DCA to be worth buffering."""
    if _RADIUS_NM <= 0:
        return True
    try:
        return haversine_nm(DCA_LAT, DCA_LON, lat, lon) <= _RADIUS_NM
    except (TypeError, ValueError):
        return False


def record_snapshot(aircraft_list: List[Dict[str, Any]], ts: float) -> None:
    """Append the current position of every in-range aircraft to its ring
    buffer, and drop aircraft that are no longer present (or have left the
    radius) so memory stays bounded.

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
        if not in_range(coords[0], coords[1]):
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


def stats() -> Dict[str, int]:
    """(aircraft tracked, total fixes held) -- for /api/status style reporting."""
    return {
        "aircraft": len(_POSITIONS),
        "fixes": sum(len(b) for b in _POSITIONS.values()),
        "max_fixes": _MAX_FIXES,
        "radius_nm": int(_RADIUS_NM),
    }


def get_pre_positions(cid: str, before_ts: float, limit: int = 0) -> List[Dict[str, Any]]:
    """Return recent fixes strictly before `before_ts`, oldest first — the
    approach path leading up to a zone entry.

    `limit` of 0 (the default) returns everything buffered, which is the whole
    point: the buffer length is the bound, so callers don't need to guess.
    """
    buf = _POSITIONS.get(str(cid))
    if not buf:
        return []
    before = [dict(p) for p in buf if p.get("ts") is not None and p["ts"] < before_ts]
    before.sort(key=lambda x: x["ts"])  # oldest first
    if limit and len(before) > limit:
        before = before[-limit:]
    return before


def clear() -> None:
    _POSITIONS.clear()
