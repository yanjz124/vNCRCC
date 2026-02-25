"""In-memory ring buffer for the last N VATSIM snapshots.

Replaces DB queries during the precompute critical path.
The buffer is updated in _on_fetch before background work starts,
so precompute_all can read it without hitting the database.
"""
from collections import deque
from typing import Any, Dict, List

# Capacity of 2 matches the P56 intrusion detection requirement
_BUFFER: deque = deque(maxlen=2)


def push(data: Dict[str, Any], ts: float) -> None:
    """Add a new snapshot to the ring buffer."""
    _BUFFER.append({"data": data, "fetched_at": ts})


def get_latest(n: int = 2) -> List[Dict[str, Any]]:
    """Return the most recent N snapshots (newest first).

    Drop-in replacement for STORAGE.get_latest_snapshots(n).
    """
    items = list(_BUFFER)
    items.reverse()
    return items[:n]
