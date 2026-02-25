import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("vncrcc.sfra_history")

HISTORY_PATH = Path.cwd() / "data" / "sfra_history.json"


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
        HISTORY_PATH.write_text(json.dumps(data, separators=(',', ':'), default=str))
    except Exception as e:
        logger.error("Error writing SFRA history: %s", e)


def get_history() -> Dict[str, Any]:
    return _load()


def update_history(cid: str, position: Dict[str, Any]) -> None:
    """Update history for a CID with a new position snapshot."""
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