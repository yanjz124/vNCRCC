import json
import time
from pathlib import Path
from typing import Any, Dict, List

HISTORY_PATH = Path.cwd() / "data" / "aircraft_history.json"


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
    _ensure_parent()
    try:
        HISTORY_PATH.write_text(json.dumps(data, indent=2, sort_keys=True, default=str))
        print(f"Aircraft history written to {HISTORY_PATH}")
    except Exception as e:
        print(f"Error writing aircraft history: {e}")


def get_history() -> Dict[str, Any]:
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
            print(f"Removed {len(cids_to_remove)} aircraft from history (out of range)")

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
    print(f"Updated aircraft history for {len(updates)} aircraft (total tracked: {len(history)})")