import json
import os
import time
from typing import Any, Dict, List, Optional

try:
    # Prefer SQLAlchemy implementation when available
    from sqlalchemy import (
        create_engine,
        MetaData,
        Table,
        Column,
        Integer,
        Float,
        Text,
        String,
        JSON,
        select,
        insert,
        text,
    )
    from sqlalchemy.engine import Engine
    from sqlalchemy.exc import SQLAlchemyError
    HAS_SQLALCHEMY = True
except Exception:
    HAS_SQLALCHEMY = False

import sqlite3

if HAS_SQLALCHEMY:
    # The full SQLAlchemy-backed Storage implementation is provided in
    # `storage_sqlalchemy.py`. Import it lazily to keep this loader small.
    from .storage_sqlalchemy import Storage, STORAGE  # type: ignore
    __all__ = ["Storage", "STORAGE"]
else:
    # Fallback sqlite-only Storage for environments without SQLAlchemy.
    class Storage:
        """Simple sqlite-backed storage for snapshots and incidents.

        This fallback keeps the original sqlite3-based API used by tests and
        small deployments. It mirrors the legacy behavior and surface area.
        """

        def __init__(self, db_path: str = "vncrcc.db") -> None:
            self.db_path = db_path
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            try:
                cur = self.conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL;")
                cur.execute("PRAGMA synchronous=NORMAL;")
                cur.execute("PRAGMA busy_timeout=5000;")
            except Exception:
                pass
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
                name TEXT,
                lat REAL,
                lon REAL,
                altitude REAL,
                zone TEXT,
                evidence TEXT
            )
            """
            )
            # Migration: add name column if it doesn't exist
            try:
                cur.execute("ALTER TABLE incidents ADD COLUMN name TEXT")
                self.conn.commit()
            except Exception:
                pass  # Column already exists
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
            # Only track positions if enabled (expensive on sqlite)
            if os.getenv("VNCRCC_TRACK_POSITIONS", "0").strip() == "1":
                self._save_aircraft_positions(data, fetched_at)
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
            cur = self.conn.cursor()
            cur.execute("SELECT raw_json, fetched_at FROM snapshots ORDER BY fetched_at DESC LIMIT ?", (limit,))
            rows = cur.fetchall()
            out: List[Dict[str, Any]] = []
            for raw, ts in rows:
                out.append({"data": json.loads(raw), "fetched_at": ts})
            return out

        def get_latest_snapshots(self, n: int = 2) -> List[Dict[str, Any]]:
            return self.list_snapshots(limit=n)

        def _cleanup_old_snapshots(self, keep_recent: int = 5) -> None:
            cur = self.conn.cursor()
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
                    pass
            self.conn.commit()
            self._cleanup_old_positions()

        def _cleanup_old_positions(self) -> None:
            cur = self.conn.cursor()
            try:
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
            except Exception:
                try:
                    cur.execute("VACUUM")
                    self.conn.commit()
                except Exception:
                    pass

        def get_aircraft_positions(self, cid: str, since: Optional[float] = None, limit: int = 10) -> List[Dict[str, Any]]:
            """Get position history for a specific aircraft CID.
            
            Args:
                cid: Aircraft CID
                since: Optional timestamp to get positions after
                limit: Maximum number of positions to return (default 10)
            
            Returns:
                List of position dicts with keys: ts, lat, lon, alt, gs, heading, callsign
            """
            cur = self.conn.cursor()
            if since is not None:
                cur.execute(
                    "SELECT timestamp, latitude, longitude, altitude, groundspeed, heading, callsign FROM aircraft_positions WHERE cid = ? AND timestamp >= ? ORDER BY timestamp ASC LIMIT ?",
                    (cid, since, limit)
                )
            else:
                cur.execute(
                    "SELECT timestamp, latitude, longitude, altitude, groundspeed, heading, callsign FROM aircraft_positions WHERE cid = ? ORDER BY timestamp DESC LIMIT ?",
                    (cid, limit)
                )
            rows = cur.fetchall()
            positions = []
            for row in rows:
                positions.append({
                    "ts": row[0],
                    "lat": row[1],
                    "lon": row[2],
                    "alt": row[3],
                    "gs": row[4],
                    "heading": row[5],
                    "callsign": row[6]
                })
            return positions

        def save_incident(self, detected_at: float, callsign: str, cid: Optional[int], lat: float, lon: float, altitude: Optional[float], zone: str, evidence: str, name: Optional[str] = None) -> int:
            cur = self.conn.cursor()
            cur.execute(
                "INSERT INTO incidents (detected_at, callsign, cid, name, lat, lon, altitude, zone, evidence) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (detected_at, callsign, cid, name, lat, lon, altitude, zone, evidence),
            )
            self.conn.commit()
            return cur.lastrowid or 0

        def update_incident(self, id: int, evidence: str) -> None:
            cur = self.conn.cursor()
            cur.execute("UPDATE incidents SET evidence = ? WHERE id = ?", (evidence, id))
            self.conn.commit()

        def get_aircraft_position_history(self, cid: int, limit: int = 10) -> List[Dict[str, Any]]:
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

        def list_incidents(self, limit: int = 100) -> List[Dict[str, Any]]:
            cur = self.conn.cursor()
            cur.execute("SELECT id, detected_at, callsign, cid, name, lat, lon, altitude, zone, evidence FROM incidents ORDER BY detected_at DESC LIMIT ?", (limit,))
            rows = cur.fetchall()
            out = []
            for r in rows:
                out.append({
                    "id": r[0],
                    "detected_at": r[1],
                    "callsign": r[2],
                    "cid": r[3],
                    "name": r[4],
                    "lat": r[5],
                    "lon": r[6],
                    "altitude": r[7],
                    "zone": r[8],
                    "evidence": r[9]
                })
            return out

        def list_aircraft(self) -> List[Dict[str, Any]]:
            """Return latest aircraft snapshot without per-CID history lookups.

            Per-request N+1 history queries are very expensive on sqlite and not
            needed for the main UI. The dedicated endpoint `/api/v1/aircraft/list/history`
            serves history when required.
            """
            snap = self.get_latest_snapshot()
            if not snap:
                return []
            data = snap.get("data")
            if not data:
                return []
            aircraft = data.get("pilots") or data.get("aircraft") or []
            return aircraft

        def save_classification(self, snapshot_id: int, typ: str, summary: Any) -> None:
            # Not supported in fallback sqlite-only storage for now; noop
            return None

        def get_latest_classification(self, typ: str) -> Optional[Any]:
            return None

    # Module-level default STORAGE singleton for fallback
    try:
        STORAGE = Storage()
    except Exception:
        STORAGE = None

    __all__ = ["Storage", "STORAGE"]
