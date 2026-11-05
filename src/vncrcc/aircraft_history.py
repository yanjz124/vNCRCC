import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("vncrcc.aircraft_history")

HISTORY_PATH = Path.cwd() / "data" / "aircraft_history.json"

# PERF: Cache for get_history() to avoid repeated file reads
_HISTORY_CACHE: Optional[Dict[str, Any]] = None
_HISTORY_CACHE_MTIME: float = 0


def _ensure_parent():
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)


def _load() -> Dict[str, Any]:
    _ensure_parent()
    if not HISTORY_PATH.exists():
        return {}
    try:
        return json.loads(HISTORY_PATH.read_text())
    except Exception:
        return {}


def _atomic_write(data: Dict[str, Any]):
    global _HISTORY_CACHE, _HISTORY_CACHE_MTIME
    _ensure_parent()
    try:
        # PERF: Use compact JSON (no indent) to reduce file size and write time
        # Write-then-rename so concurrent readers (dashboard, P-56 fallback)
        # never parse a half-written file -- _load() maps that to {} and the
        # mtime cache would then serve the empty history.
        tmp = HISTORY_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, separators=(',', ':'), default=str))
        tmp.replace(HISTORY_PATH)
        # PERF: Removed verbose logging - this runs every 15s and clutters logs
        # Invalidate cache after write
        _HISTORY_CACHE = None
        _HISTORY_CACHE_MTIME = 0
    except Exception as e:
        logger.error("Error writing aircraft history: %s", e)


def get_history() -> Dict[str, Any]:
    """Get aircraft history with caching to avoid repeated file reads.

    PERF: Caches the history file and only reloads if file has been modified.
    This is safe because history updates always call _atomic_write which changes mtime.
    """
    global _HISTORY_CACHE, _HISTORY_CACHE_MTIME

    # The JSON history is only written with VNCRCC_WRITE_JSON_HISTORY=1, which
    # production doesn't set -- so clicked flight paths had no data at all.
    # Serve the always-on in-memory tracker instead whenever the file is
    # absent or empty (no disk I/O on this path).
    try:
        if not HISTORY_PATH.exists() or HISTORY_PATH.stat().st_size == 0:
            from .position_history import get_tracks
            return {"history": get_tracks()}

        # Check if file has been modified since last cache
        current_mtime = HISTORY_PATH.stat().st_mtime
        if _HISTORY_CACHE is not None and current_mtime == _HISTORY_CACHE_MTIME:
            return _HISTORY_CACHE

        # File changed or no cache - reload
        data = _load()
        _HISTORY_CACHE = data
        _HISTORY_CACHE_MTIME = current_mtime
        return data
    except Exception:
        # Fallback to uncached load on error
        return _load()


def update_history(cid: str, position: Dict[str, Any]) -> None:
    """Update history for a CID with a new position snapshot (keep last 10)."""
    data = _load()
    history: Dict[str, List[Dict[str, Any]]] = data.setdefault("history", {})

    if cid not in history:
        history[cid] = []

    # Add new position
    pos_copy = dict(position)
    pos_copy.setdefault("ts", time.time())
    history[cid].append(pos_copy)

    # Keep only last 10
    history[cid] = history[cid][-10:]

    _atomic_write(data)


def get_history_for_cid(cid: str) -> List[Dict[str, Any]]:
    """Get position history for a specific CID.
    
    Args:
        cid: Aircraft CID (as string)
    
    Returns:
        List of position dictionaries with keys: lat, lon, alt, ts, callsign
    """
    data = _load()
    history: Dict[str, List[Dict[str, Any]]] = data.get("history", {})
    return history.get(cid, [])


def update_history_batch(updates: Dict[str, Dict[str, Any]], filtered_cids: set = None) -> None:
    """Update history for multiple CIDs in a single batch operation.
    
    Args:
        updates: Dictionary of CID -> position data to update
        filtered_cids: Set of CIDs that are currently in the filtered list (within range).
                      If provided, CIDs not in this set will be removed from history.
    """
    data = _load()
    history: Dict[str, List[Dict[str, Any]]] = data.setdefault("history", {})

    # Remove CIDs that are no longer in the filtered set
    if filtered_cids is not None:
        cids_to_remove = [cid for cid in history.keys() if cid not in filtered_cids]
        for cid in cids_to_remove:
            del history[cid]
        if cids_to_remove:
            logger.debug("Removed %d aircraft from history (out of range)", len(cids_to_remove))

    for cid, position in updates.items():
        if cid not in history:
            history[cid] = []

        # Add new position
        pos_copy = dict(position)
        pos_copy.setdefault("ts", time.time())
        history[cid].append(pos_copy)

        # Keep only last 10
        history[cid] = history[cid][-10:]

    _atomic_write(data)