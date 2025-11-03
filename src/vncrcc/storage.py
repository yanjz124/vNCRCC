import json
import sqlite3
import time
from typing import Any, Dict, List, Optional


class Storage:
    """Simple sqlite-backed storage for snapshots and incidents.

    This is intentionally minimal to keep the initial prototype small and
    easy to run on a Raspberry Pi. It stores raw JSON snapshots and allows
    reading the latest snapshot for other modules.
    """

    def __init__(self, db_path: str = "vncrcc.db") -> None:
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_db()

    def _init_db(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY,
            fetched_at REAL,
            raw_json TEXT
        )
        """
        )
        cur.execute(
            """
        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY,
            detected_at REAL,
            callsign TEXT,
            cid INTEGER,
            lat REAL,
            lon REAL,
            altitude REAL,
            zone TEXT,
            evidence TEXT
        )
        """
        )
        self.conn.commit()

    def save_snapshot(self, data: Dict[str, Any], fetched_at: Optional[float] = None) -> int:
        if fetched_at is None:
            fetched_at = time.time()
        cur = self.conn.cursor()
        cur.execute("INSERT INTO snapshots (fetched_at, raw_json) VALUES (?, ?)", (fetched_at, json.dumps(data)))
        self.conn.commit()
        return cur.lastrowid

    def get_latest_snapshot(self) -> Optional[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("SELECT raw_json, fetched_at FROM snapshots ORDER BY fetched_at DESC LIMIT 1")
        row = cur.fetchone()
        if not row:
            return None
        raw, ts = row
        return {"data": json.loads(raw), "fetched_at": ts}

    def list_aircraft(self) -> List[Dict[str, Any]]:
        snap = self.get_latest_snapshot()
        if not snap:
            return []
        data = snap.get("data")
        # VATSIM v3 places flights/aircraft under 'pilots' or 'aircraft' depending on feed
        aircraft = data.get("pilots") or data.get("aircraft") or []
        return aircraft


__all__ = ["Storage"]
