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
        sid = cur.lastrowid or 0
        
        # Keep only the most recent 100 snapshots to prevent unlimited growth
        self._cleanup_old_snapshots()
        
        return sid

    def get_latest_snapshot(self) -> Optional[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("SELECT raw_json, fetched_at FROM snapshots ORDER BY fetched_at DESC LIMIT 1")
        row = cur.fetchone()
        if not row:
            return None
        raw, ts = row
        return {"data": json.loads(raw), "fetched_at": ts}

    def list_snapshots(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Return up to `limit` most recent snapshots as list of {data, fetched_at}."""
        cur = self.conn.cursor()
        cur.execute("SELECT raw_json, fetched_at FROM snapshots ORDER BY fetched_at DESC LIMIT ?", (limit,))
        rows = cur.fetchall()
        out: List[Dict[str, Any]] = []
        for raw, ts in rows:
            out.append({"data": json.loads(raw), "fetched_at": ts})
        return out

    def get_latest_snapshots(self, n: int = 2) -> List[Dict[str, Any]]:
        """Convenience: return the latest `n` snapshots (most recent first)."""
        return self.list_snapshots(limit=n)

    def _cleanup_old_snapshots(self, keep_recent: int = 100) -> None:
        """Keep only the most recent N snapshots to prevent unlimited database growth."""
        cur = self.conn.cursor()
        # Delete snapshots older than the 100th most recent
        cur.execute("""
            DELETE FROM snapshots 
            WHERE id NOT IN (
                SELECT id FROM snapshots 
                ORDER BY fetched_at DESC 
                LIMIT ?
            )
        """, (keep_recent,))
        self.conn.commit()

    def save_incident(self, detected_at: float, callsign: str, cid: Optional[int], lat: float, lon: float, altitude: Optional[float], zone: str, evidence: str) -> int:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO incidents (detected_at, callsign, cid, lat, lon, altitude, zone, evidence) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (detected_at, callsign, cid, lat, lon, altitude, zone, evidence),
        )
        self.conn.commit()
        return cur.lastrowid or 0

    def list_incidents(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Return up to `limit` most recent incidents as list of dicts."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT id, detected_at, callsign, cid, lat, lon, altitude, zone, evidence FROM incidents ORDER BY detected_at DESC LIMIT ?",
            (limit,),
        )
        rows = cur.fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            id_, detected_at, callsign, cid, lat, lon, altitude, zone, evidence = r
            out.append(
                {
                    "id": id_,
                    "detected_at": detected_at,
                    "callsign": callsign,
                    "cid": cid,
                    "lat": lat,
                    "lon": lon,
                    "altitude": altitude,
                    "zone": zone,
                    "evidence": evidence,
                }
            )
        return out

    def list_aircraft(self) -> List[Dict[str, Any]]:
        snap = self.get_latest_snapshot()
        if not snap:
            return []
        data = snap.get("data")
        if not data:
            return []
        # VATSIM v3 places flights/aircraft under 'pilots' or 'aircraft' depending on feed
        aircraft = data.get("pilots") or data.get("aircraft") or []
        return aircraft


__all__ = ["Storage"]

# Module-level default STORAGE singleton for convenience. Other modules import
# this when they need access to the DB. Using a small global is acceptable for
# this prototype; it will be replaced with a proper dependency-injection
# strategy if the project grows.
try:
    STORAGE = Storage()
except Exception:
    # If the DB cannot be opened at import time, set STORAGE to None so callers
    # can handle initialization errors at runtime.
    STORAGE = None
    
__all__.append("STORAGE")
