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
        cur.execute(
            """
        CREATE TABLE IF NOT EXISTS aircraft_positions (
            id INTEGER PRIMARY KEY,
            cid INTEGER,
            callsign TEXT,
            timestamp REAL,
            latitude REAL,
            longitude REAL,
            altitude REAL,
            groundspeed REAL,
            heading REAL
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
        
        # Save aircraft positions
        self._save_aircraft_positions(data, fetched_at)
        
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

    def _save_aircraft_positions(self, data: Dict[str, Any], timestamp: float) -> None:
        """Save positions for all aircraft in the snapshot."""
        aircraft = data.get("pilots") or data.get("aircraft") or []
        cur = self.conn.cursor()
        for ac in aircraft:
            try:
                cid = ac.get("cid")
                callsign = ac.get("callsign")
                lat = ac.get("latitude") or ac.get("lat")
                lon = ac.get("longitude") or ac.get("lon")
                alt = ac.get("altitude")
                gs = ac.get("groundspeed")
                heading = ac.get("heading")
                if cid is not None and lat is not None and lon is not None:
                    cur.execute(
                        "INSERT INTO aircraft_positions (cid, callsign, timestamp, latitude, longitude, altitude, groundspeed, heading) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (cid, callsign, timestamp, lat, lon, alt, gs, heading)
                    )
            except Exception:
                pass  # Skip invalid aircraft
        self.conn.commit()
        # Keep only the most recent 10 positions per aircraft
        self._cleanup_old_positions()

    def _cleanup_old_positions(self) -> None:
        """Keep only the most recent 10 positions per aircraft."""
        cur = self.conn.cursor()
        # Delete positions older than the 10th most recent for each cid
        cur.execute("""
            DELETE FROM aircraft_positions 
            WHERE id NOT IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (PARTITION BY cid ORDER BY timestamp DESC) as rn
                    FROM aircraft_positions
                ) WHERE rn <= 10
            )
        """)
        self.conn.commit()

    def save_incident(self, detected_at: float, callsign: str, cid: Optional[int], lat: float, lon: float, altitude: Optional[float], zone: str, evidence: str) -> int:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO incidents (detected_at, callsign, cid, lat, lon, altitude, zone, evidence) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (detected_at, callsign, cid, lat, lon, altitude, zone, evidence),
        )
        self.conn.commit()
        return cur.lastrowid or 0

    def update_incident(self, id: int, evidence: str) -> None:
        cur = self.conn.cursor()
        cur.execute("UPDATE incidents SET evidence = ? WHERE id = ?", (evidence, id))
        self.conn.commit()

    def get_aircraft_position_history(self, cid: int, limit: int = 10) -> List[Dict[str, Any]]:
        """Get the most recent position history for an aircraft."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT timestamp, latitude, longitude, altitude, groundspeed, heading FROM aircraft_positions WHERE cid = ? ORDER BY timestamp DESC LIMIT ?",
            (cid, limit)
        )
        rows = cur.fetchall()
        history = []
        for ts, lat, lon, alt, gs, hdg in rows:
            history.append({
                "timestamp": ts,
                "latitude": lat,
                "longitude": lon,
                "altitude": alt,
                "groundspeed": gs,
                "heading": hdg
            })
        return history

    def list_aircraft(self) -> List[Dict[str, Any]]:
        snap = self.get_latest_snapshot()
        if not snap:
            return []
        data = snap.get("data")
        if not data:
            return []
        # VATSIM v3 places flights/aircraft under 'pilots' or 'aircraft' depending on feed
        aircraft = data.get("pilots") or data.get("aircraft") or []
        # Add position history to each aircraft
        for ac in aircraft:
            cid = ac.get("cid")
            if cid is not None:
                ac["position_history"] = self.get_aircraft_position_history(cid, 10)
            else:
                ac["position_history"] = []
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
