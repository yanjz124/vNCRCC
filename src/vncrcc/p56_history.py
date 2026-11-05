import json
import logging
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .geo.loader import point_from_aircraft

# Anchor to the repo root (not the process CWD, which differs between the two
# systemd overrides in this repo) unless overridden. If an older file exists
# under the CWD and not at the repo root, keep using it so a deploy never
# "loses" the log by switching files.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_PATH = os.environ.get("VNCRCC_P56_HISTORY_PATH")
if _ENV_PATH:
    HISTORY_PATH = Path(_ENV_PATH)
else:
    HISTORY_PATH = _REPO_ROOT / "data" / "p56_history.json"
    _legacy = Path.cwd() / "data" / "p56_history.json"
    if not HISTORY_PATH.exists() and _legacy.exists():
        HISTORY_PATH = _legacy

# If an aircraft re-enters P56 within this many position updates after exiting,
# treat as the same intrusion (not a new one).
REENTRY_GRACE_UPDATES = 5
# Rolling backup of the last good history file, refreshed at most this often.
BACKUP_INTERVAL_S = 600

logger = logging.getLogger("vncrcc.p56_history")

# Serializes every load-modify-write of the history file. The precompute cycle
# runs in an executor thread while admin clear/purge run on the event loop;
# without this an in-flight cycle that loaded the file before a purge would
# write the purged events straight back (and both writers shared one .tmp).
_LOCK = threading.RLock()

# PERF: Cache for get_history() to avoid repeated file reads
_HISTORY_CACHE: Optional[Dict[str, Any]] = None
_HISTORY_CACHE_MTIME: float = 0
# Last successfully parsed history, served to readers if the file goes bad.
_LAST_GOOD: Optional[Dict[str, Any]] = None


class HistoryUnreadable(RuntimeError):
    """The history file exists but can't be parsed. Writers must NOT proceed:
    treating it as empty and saving would wipe the intrusion log/leaderboard."""


def _path() -> Path:
    # Accept either a pathlib.Path or a string (tests set a string path).
    return HISTORY_PATH if isinstance(HISTORY_PATH, Path) else Path(HISTORY_PATH)


def _backup_path() -> Path:
    return _path().with_suffix(".json.bak")


def _ensure_parent():
    _path().parent.mkdir(parents=True, exist_ok=True)


def _parse(p: Path) -> Dict[str, Any]:
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("history root is not an object")
    data.setdefault("events", [])
    data.setdefault("current_inside", {})
    return data


def _load() -> Dict[str, Any]:
    """Load history. A *missing* file is a genuinely empty history; a file that
    exists but fails to parse is NOT -- it used to be mapped to {} here, and the
    next poll cycle then wrote {} back, silently wiping every event (the
    "log and leaderboard purge themselves" bug). Now we retry, fall back to the
    rolling backup, and otherwise raise so callers skip the write."""
    _ensure_parent()
    p = _path()
    if not p.exists():
        return {"events": [], "current_inside": {}}
    bak = _backup_path()
    try:
        zero_length = p.stat().st_size == 0
    except OSError:
        zero_length = False
    if zero_length:
        # A 0-byte file is what ext4 can leave after a power cut when a rename
        # wasn't preceded by fsync (the old writer didn't fsync). Restore from
        # backup if we have one; otherwise there's genuinely nothing to lose.
        if bak.exists():
            try:
                data = _parse(bak)
                logger.error("P-56 history %s was empty; restored %d events from %s", p, len(data["events"]), bak.name)
                return data
            except Exception:
                logger.exception("P-56 history backup %s is unreadable", bak.name)
        return {"events": [], "current_inside": {}}
    last_err: Optional[Exception] = None
    for attempt in range(3):
        try:
            return _parse(p)
        except Exception as e:  # transient partial read, encoding glitch, ...
            last_err = e
            time.sleep(0.05 * (attempt + 1))
    bak = _backup_path()
    try:
        # Keep the unreadable file IN PLACE (moving it would make the next
        # cycle see "no file" and start an empty history -- the same wipe one
        # cycle later) and save one copy for inspection, named by its mtime so
        # repeated failed loads don't create a copy every 10s.
        corrupt = p.with_suffix(f".json.corrupt-{int(p.stat().st_mtime)}")
        if not corrupt.exists():
            shutil.copy2(p, corrupt)
            logger.error("P-56 history %s unreadable (%s); copy saved as %s", p, last_err, corrupt.name)
    except Exception:
        logger.exception("P-56 history %s unreadable (%s) and could not be copied", p, last_err)
    if bak.exists():
        try:
            data = _parse(bak)
            logger.error("Restored P-56 history from backup %s (%d events)", bak.name, len(data["events"]))
            return data
        except Exception:
            logger.exception("P-56 history backup %s is unreadable too", bak.name)
    raise HistoryUnreadable(f"{p} could not be parsed: {last_err}")


def _atomic_write(data: Dict[str, Any]):
    global _HISTORY_CACHE, _HISTORY_CACHE_MTIME
    _ensure_parent()
    p = _path()
    # Refresh the rolling backup from the current (known-good) file before
    # replacing it, at most every BACKUP_INTERVAL_S.
    try:
        bak = _backup_path()
        if p.exists() and (not bak.exists() or time.time() - bak.stat().st_mtime > BACKUP_INTERVAL_S):
            _parse(p)  # only back up a file that actually parses
            shutil.copy2(p, bak)
    except Exception:
        logger.warning("Could not refresh P-56 history backup", exc_info=True)
    tmp = p.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    # PERF: Use compact JSON (no indent) to reduce file size and write time
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, separators=(',', ':'), default=str))
        f.flush()
        os.fsync(f.fileno())  # survive power loss on the Pi's SD card
    tmp.replace(p)
    # Invalidate cache after write
    _HISTORY_CACHE = None
    _HISTORY_CACHE_MTIME = 0


def get_history() -> Dict[str, Any]:
    """Get P56 history with caching to avoid repeated file reads.

    PERF: Caches the history file and only reloads if file has been modified.
    This is safe because history updates always call _atomic_write which changes mtime.
    """
    global _HISTORY_CACHE, _HISTORY_CACHE_MTIME, _LAST_GOOD

    try:
        p = HISTORY_PATH if isinstance(HISTORY_PATH, Path) else Path(HISTORY_PATH)
        if not p.exists():
            return {"events": [], "current_inside": {}}

        # Check if file has been modified since last cache
        current_mtime = p.stat().st_mtime
        if _HISTORY_CACHE is not None and current_mtime == _HISTORY_CACHE_MTIME:
            return _HISTORY_CACHE

        # File changed or no cache - reload
        data = _load()
        _HISTORY_CACHE = data
        _LAST_GOOD = data
        _HISTORY_CACHE_MTIME = current_mtime
        return data
    except HistoryUnreadable:
        # Serve the last good copy rather than an empty log.
        return _LAST_GOOD or {"events": [], "current_inside": {}}
    except Exception:
        # Fallback to uncached load on error
        try:
            return _load()
        except HistoryUnreadable:
            return _LAST_GOOD or {"events": [], "current_inside": {}}


def build_event_track(event: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flatten an intrusion event's stored positions into a single ordered path.

    Combines the three position buckets in chronological order so a consumer
    (e.g. the Discord bot) can draw the whole trajectory on a map:

        pre_positions        -> approach BEFORE entering P-56
        intrusion_positions  -> track while inside P-56
        post_positions       -> departure AFTER exiting P-56

    Each bucket is already stored oldest-first. Every point is tagged with a
    ``phase`` so the path can be styled (e.g. approach vs. inside the zone).
    """
    track: List[Dict[str, Any]] = []
    for phase, key in (
        ("pre", "pre_positions"),
        ("intrusion", "intrusion_positions"),
        ("post", "post_positions"),
    ):
        for p in event.get(key) or []:
            lat = p.get("lat")
            lon = p.get("lon")
            if lat is None or lon is None:
                continue
            track.append({
                "lat": lat,
                "lon": lon,
                "ts": p.get("ts"),
                "alt": p.get("alt"),
                "gs": p.get("gs"),
                "heading": p.get("heading"),
                "phase": phase,
            })
    return track


def get_history_for_api(include_track: bool = True) -> Dict[str, Any]:
    """Return history shaped for external API consumers.

    - ``events`` are sorted most-recent-first (by recorded_at / latest_ts).
    - When ``include_track`` is set, each event gains a flattened ``track``
      containing the full approach + intrusion + departure path so callers can
      render the trajectory directly.

    A shallow copy is returned; the cached history is never mutated.
    """
    hist = get_history()
    events = list(hist.get("events") or [])
    events.sort(
        key=lambda e: (e.get("recorded_at") or e.get("latest_ts") or 0),
        reverse=True,
    )
    if include_track:
        enriched: List[Dict[str, Any]] = []
        for e in events:
            e2 = dict(e)
            e2["track"] = build_event_track(e)
            enriched.append(e2)
        events = enriched
    return {"events": events, "current_inside": hist.get("current_inside", {})}


def clear_history() -> None:
    """Clear all recorded P-56 events and current_inside state.

    This overwrites the history file with an empty structure. Use with
    caution — this is irreversible.
    """
    with _LOCK:
        _atomic_write({"events": [], "current_inside": {}})


def _purge_events_unlocked(keys: Optional[List[str]] = None, items: Optional[List[Dict[str, Any]]] = None) -> Dict[str, int]:
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


def _record_penetration_unlocked(event: Dict[str, Any], skip_write: bool = False) -> None:
    """Record a new penetration event. Event should include at least 'cid' or 'identifier'.

    Args:
        event: Event dict containing cid, position, etc.
        skip_write: If True, don't write to disk (for batching with sync_snapshot)
    """
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

    # Deduplicate: if the CID is still tracked (p56_buster=True) and within the
    # grace period (outside_count < REENTRY_GRACE_UPDATES), merge re-entry into
    # the existing event so quick re-entries count as a single buster.
    if state and state.get("p56_buster") and state.get("outside_count", 0) < REENTRY_GRACE_UPDATES:
        last_event = None
        for e in reversed(events):
            if str(e.get("cid")) == str(cid):
                last_event = e
                break

        if last_event:
            # Re-entry within grace period — merge into existing event
            # Update latest_ts
            new_ts = event_copy.get("latest_ts")
            if new_ts is not None:
                prev_ts = last_event.get("latest_ts")
                try:
                    new_ts_f = float(new_ts)
                    prev_ts_f = float(prev_ts) if prev_ts is not None else None
                    if prev_ts_f is None or new_ts_f > prev_ts_f:
                        last_event["latest_ts"] = new_ts
                except Exception:
                    pass
            # Union zones (accumulate all zones visited)
            existing_zones = set(last_event.get("zones", []))
            existing_zones.update(event_copy.get("zones", []))
            last_event["zones"] = sorted(existing_zones)
            # Move post_positions back into intrusion_positions (they're mid-intrusion now)
            post = last_event.pop("post_positions", [])
            if post:
                ip = last_event.get("intrusion_positions", [])
                ip.extend(post)
                last_event["intrusion_positions"] = ip
            # Clear exit_detected_at since they re-entered
            last_event.pop("exit_detected_at", None)
            # Merge pre_positions if not already present
            if event_copy.get("pre_positions") and not last_event.get("pre_positions"):
                last_event["pre_positions"] = event_copy["pre_positions"]
            # Reset current_inside state for continued tracking
            current[str(cid)] = {
                "inside": True,
                "p56_buster": True,
                "outside_count": 0,
                "last_seen": event_copy.get("latest_ts") or event_copy.get("recorded_at"),
                "last_position": event_copy.get("latest_position"),
                "flight_plan": event_copy.get("flight_plan", {}),
                "callsign": event_copy.get("callsign") or event_copy.get("flight_plan", {}).get("callsign"),
                "name": event_copy.get("name"),
                "zones": last_event["zones"]
            }
            if not skip_write:
                _atomic_write(data)
            return

    events.append(event_copy)

    # Seed intrusion_positions with ONLY the initial position inside P56 (not pre_positions)
    # pre_positions are kept separate and should not be duplicated here
    seed_positions: List[Dict[str, Any]] = []
    lp = event_copy.get("latest_position")
    ts_lp = event_copy.get("latest_ts") or event_copy.get("recorded_at")
    if lp and ts_lp is not None:
        seed_positions.append({
            "ts": ts_lp,
            "lat": lp.get("lat"),
            "lon": lp.get("lon"),
            "alt": event_copy.get("altitude") or event_copy.get("alt"),
            "gs": event_copy.get("groundspeed") or event_copy.get("gs"),
            "heading": event_copy.get("heading"),
            "callsign": event_copy.get("callsign")
        })
    event_copy["intrusion_positions"] = seed_positions

    # mark current inside with p56_buster flag for continuous tracking
    current[str(cid)] = {
        "inside": True,
        "p56_buster": True,
        "outside_count": 0,
        "last_seen": event_copy.get("latest_ts") or event_copy.get("recorded_at"),
        "last_position": event_copy.get("latest_position"),
        "flight_plan": event_copy.get("flight_plan", {}),
        "callsign": event_copy.get("callsign") or event_copy.get("flight_plan", {}).get("callsign"),
        "name": event_copy.get("name"),
        "zones": event_copy.get("zones", [])
    }

    # PERF: Only write if not batching with sync_snapshot
    if not skip_write:
        _atomic_write(data)


def _mark_exit_unlocked(cid: str, ts: Optional[float] = None) -> None:
    data = _load()
    current: Dict[str, Any] = data.setdefault("current_inside", {})
    if str(cid) in current:
        current[str(cid)]["inside"] = False
        current[str(cid)]["last_seen"] = ts or time.time()
        _atomic_write(data)


def _sync_snapshot_with_penetrations_unlocked(
    aircraft_list: List[Dict[str, Any]],
    features: List,
    ts: Optional[float] = None,
    penetration_events: Optional[List[Dict[str, Any]]] = None,
    positions_by_cid: Optional[Dict[str, List]] = None
) -> None:
    """Batch process penetration events AND position tracking in single file write.

    PERF: This function combines record_penetration logic with sync_snapshot to eliminate
    redundant file I/O. Instead of N+1 writes per cycle (N penetrations + 1 sync), we do 1 write.

    Args:
        aircraft_list: Current VATSIM aircraft
        features: P-56 zone shapes
        ts: Timestamp
        penetration_events: List of new penetration events to record (batched)
        positions_by_cid: Position history for trajectory tracking
    """
    # PERF: Load data once at the start
    data = _load()
    current: Dict[str, Any] = data.setdefault("current_inside", {})
    events: List[Dict[str, Any]] = data.setdefault("events", [])

    # Process all penetration events first (record_penetration logic inlined)
    if penetration_events:
        for event in penetration_events:
            cid = event.get("cid") or event.get("identifier")
            if not cid:
                cid = f"NOCID-{int(time.time())}"
                event["cid"] = cid

            # If already marked inside, skip duplicate
            state = current.get(str(cid))
            if state and state.get("inside"):
                continue

            event_copy = dict(event)
            event_copy.setdefault("recorded_at", time.time())

            # Deduplicate: if CID is still tracked and within grace period, merge re-entry
            if state and state.get("p56_buster") and state.get("outside_count", 0) < REENTRY_GRACE_UPDATES:
                last_event = None
                for e in reversed(events):
                    if str(e.get("cid")) == str(cid):
                        last_event = e
                        break

                if last_event:
                    # Re-entry within grace period — merge into existing event
                    new_ts = event_copy.get("latest_ts")
                    if new_ts is not None:
                        prev_ts = last_event.get("latest_ts")
                        try:
                            new_ts_f = float(new_ts)
                            prev_ts_f = float(prev_ts) if prev_ts is not None else None
                            if prev_ts_f is None or new_ts_f > prev_ts_f:
                                last_event["latest_ts"] = new_ts
                        except Exception:
                            pass
                    # Union zones
                    existing_zones = set(last_event.get("zones", []))
                    existing_zones.update(event_copy.get("zones", []))
                    last_event["zones"] = sorted(existing_zones)
                    # Move post_positions back into intrusion_positions
                    post = last_event.pop("post_positions", [])
                    if post:
                        ip = last_event.get("intrusion_positions", [])
                        ip.extend(post)
                        last_event["intrusion_positions"] = ip
                    last_event.pop("exit_detected_at", None)
                    if event_copy.get("pre_positions") and not last_event.get("pre_positions"):
                        last_event["pre_positions"] = event_copy["pre_positions"]
                    current[str(cid)] = {
                        "inside": True,
                        "p56_buster": True,
                        "outside_count": 0,
                        "last_seen": event_copy.get("latest_ts") or event_copy.get("recorded_at"),
                        "last_position": event_copy.get("latest_position"),
                        "flight_plan": event_copy.get("flight_plan", {}),
                        "callsign": event_copy.get("callsign") or event_copy.get("flight_plan", {}).get("callsign"),
                        "name": event_copy.get("name"),
                        "zones": last_event["zones"]
                    }
                    continue

            # New event - append to events list
            events.append(event_copy)

            # Seed intrusion_positions with ONLY the initial position inside P56 (not pre_positions)
            # pre_positions are kept separate and should not be duplicated here
            seed_positions: List[Dict[str, Any]] = []
            lp = event_copy.get("latest_position")
            ts_lp = event_copy.get("latest_ts") or event_copy.get("recorded_at")
            if lp and ts_lp is not None:
                seed_positions.append({
                    "ts": ts_lp,
                    "lat": lp.get("lat"),
                    "lon": lp.get("lon"),
                    "alt": event_copy.get("altitude") or event_copy.get("alt"),
                    "gs": event_copy.get("groundspeed") or event_copy.get("gs"),
                    "heading": event_copy.get("heading"),
                    "callsign": event_copy.get("callsign")
                })
            event_copy["intrusion_positions"] = seed_positions

            # Mark current inside
            current[str(cid)] = {
                "inside": True,
                "p56_buster": True,
                "outside_count": 0,
                "last_seen": event_copy.get("latest_ts") or event_copy.get("recorded_at"),
                "last_position": event_copy.get("latest_position"),
                "flight_plan": event_copy.get("flight_plan", {}),
                "callsign": event_copy.get("callsign") or event_copy.get("flight_plan", {}).get("callsign"),
                "name": event_copy.get("name"),
                "zones": event_copy.get("zones", [])
            }

    # Now continue with sync_snapshot logic (position tracking)
    _sync_snapshot_positions(aircraft_list, features, ts, positions_by_cid, data, current, events)

    # PERF: Single write at the end for all changes
    _atomic_write(data)


def _sync_snapshot_positions(
    aircraft_list: List[Dict[str, Any]],
    features: List,
    ts: Optional[float],
    positions_by_cid: Optional[Dict[str, List]],
    data: Dict[str, Any],
    current: Dict[str, Any],
    events: List[Dict[str, Any]]
) -> None:
    """Helper to update positions without file I/O (extracted from sync_snapshot)."""
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
            continue

        # Find the last event for this CID
        last_event = None
        for e in reversed(events):
            if str(e.get("cid")) == cid:
                last_event = e
                break

        if not last_event:
            current[cid]["p56_buster"] = False
            continue

        # Check if aircraft is currently inside P-56, and which zone(s)
        a = ac_map.get(str(cid))
        currently_inside = False
        current_zones: List[str] = []
        pt = None
        if a:
            pt = point_from_aircraft(a)
            if pt:
                for shp, props in features:
                    zone_name = props.get("name") or props.get("id") or "P-56"
                    try:
                        if getattr(shp, "contains", lambda x: False)(pt) or getattr(shp, "intersects", lambda x: False)(pt):
                            currently_inside = True
                            current_zones.append(zone_name)
                    except Exception:
                        continue

        if a and pt:
            current[cid].pop("missing_count", None)
            pos_entry = {
                "ts": ts or time.time(),
                "lat": pt.y,
                "lon": pt.x,
                "alt": a.get("altitude") or a.get("alt"),
                "gs": a.get("groundspeed") or a.get("gs"),
                "heading": a.get("heading"),
                "callsign": a.get("callsign")
            }

            if currently_inside:
                # Inside P56: append to intrusion_positions
                intrusion_positions = last_event.get("intrusion_positions") or []
                if not intrusion_positions or (pos_entry["ts"] - intrusion_positions[-1]["ts"]) >= 1:
                    intrusion_positions.append(pos_entry)
                    if len(intrusion_positions) > 200:
                        intrusion_positions = intrusion_positions[-200:]
                    last_event["intrusion_positions"] = intrusion_positions

                # Accumulate zones visited during this intrusion
                event_zones = set(last_event.get("zones", []))
                event_zones.update(current_zones)
                last_event["zones"] = sorted(event_zones)
                current[cid]["zones"] = last_event["zones"]
            else:
                # Outside P56 during grace period: append to post_positions
                post_positions = last_event.get("post_positions") or []
                if not post_positions or (pos_entry["ts"] - post_positions[-1]["ts"]) >= 1:
                    post_positions.append(pos_entry)
                    last_event["post_positions"] = post_positions

            # Always update name to most recent value in ALL events for this CID
            current_name = a.get("name")
            if current_name:
                current[cid]["name"] = current_name
                for e in events:
                    if str(e.get("cid")) == cid:
                        e["name"] = current_name

            if currently_inside:
                current[cid]["inside"] = True
                current[cid]["last_seen"] = ts or time.time()
                current[cid]["outside_count"] = 0
            else:
                outside_count = state.get("outside_count", 0) + 1
                current[cid]["outside_count"] = outside_count
                current[cid]["inside"] = False
                current[cid]["last_seen"] = ts or time.time()

                if not last_event.get("exit_detected_at"):
                    last_event["exit_detected_at"] = ts or time.time()

                if outside_count >= REENTRY_GRACE_UPDATES:
                    current[cid]["p56_buster"] = False
                    last_event["exit_confirmed_at"] = ts or time.time()
        elif not a:
            # Aircraft missing from this snapshot. A single dropped poll or a
            # quick reconnect used to delete the tracking state at once, so the
            # aircraft reappearing inside P-56 was logged as a *second*
            # intrusion (double-counted on the leaderboard). Give it the same
            # grace window as a brief exit; the re-entry merge path in
            # record_penetration then folds a reappearance into this event.
            missing = state.get("missing_count", 0) + 1
            current[cid]["missing_count"] = missing
            current[cid]["inside"] = False
            if missing >= REENTRY_GRACE_UPDATES:
                if last_event and not last_event.get("exit_confirmed_at"):
                    last_event["exit_confirmed_at"] = ts or time.time()
                del current[cid]
            continue

    # Clean up stale entries from current_inside
    now = ts or time.time()
    stale_threshold = 300
    stale_cids = []
    for cid, state in current.items():
        if not state.get("p56_buster", False):
            last_seen = state.get("last_seen", 0)
            if (now - last_seen) > stale_threshold:
                stale_cids.append(cid)

    for cid in stale_cids:
        del current[cid]


def sync_snapshot(aircraft_list: List[Dict[str, Any]], features: List, ts: Optional[float] = None, positions_by_cid: Optional[Dict[str, List]] = None) -> None:
    """Update current_inside flags and track positions with p56_buster logic.

    Delegates to sync_snapshot_with_penetrations (no new penetration events).
    """
    sync_snapshot_with_penetrations(
        aircraft_list, features, ts,
        penetration_events=None,
        positions_by_cid=positions_by_cid
    )


def purge_events(keys: Optional[List[str]] = None, items: Optional[List[Dict[str, Any]]] = None) -> Dict[str, int]:
    """Remove selected events by "<cid>:<recorded_at>" keys or {cid, recorded_at} items."""
    with _LOCK:
        return _purge_events_unlocked(keys=keys, items=items)


def record_penetration(event: Dict[str, Any], skip_write: bool = False) -> None:
    """Record a new penetration event (see _record_penetration_unlocked)."""
    with _LOCK:
        _record_penetration_unlocked(event, skip_write=skip_write)


def mark_exit(cid: str, ts: Optional[float] = None) -> None:
    with _LOCK:
        _mark_exit_unlocked(cid, ts)


def sync_snapshot_with_penetrations(
    aircraft_list: List[Dict[str, Any]],
    features: List,
    ts: Optional[float] = None,
    penetration_events: Optional[List[Dict[str, Any]]] = None,
    positions_by_cid: Optional[Dict[str, List]] = None
) -> None:
    """Batch penetration events + position tracking in one locked file write."""
    with _LOCK:
        _sync_snapshot_with_penetrations_unlocked(
            aircraft_list, features, ts,
            penetration_events=penetration_events,
            positions_by_cid=positions_by_cid,
        )
