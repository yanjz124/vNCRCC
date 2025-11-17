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

        def _cleanup_old_snapshots(self, keep_recent: int = 100) -> None:
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

    def _conn(self):
        return self.engine.connect()

    def save_snapshot(self, data: Dict[str, Any], fetched_at: Optional[float] = None) -> int:
        if fetched_at is None:
            fetched_at = time.time()
        try:
            with self._conn() as conn:
                result = conn.execute(insert(self.snapshots).values(fetched_at=fetched_at, raw_json=data))
                conn.commit()
                sid = int(result.inserted_primary_key[0]) if result.inserted_primary_key else 0
                # save aircraft positions
                self._save_aircraft_positions(conn, data, fetched_at)
                # cleanup old snapshots
                self._cleanup_old_snapshots(conn)
                return sid
        except Exception:
            return 0

    def get_latest_snapshot(self) -> Optional[Dict[str, Any]]:
        try:
            with self._conn() as conn:
                stmt = select(self.snapshots.c.raw_json, self.snapshots.c.fetched_at).order_by(self.snapshots.c.fetched_at.desc()).limit(1)
                row = conn.execute(stmt).fetchone()
                if not row:
                    return None
                raw, ts = row
                return {"data": raw, "fetched_at": ts}
        except Exception:
            return None

    def list_snapshots(self, limit: int = 10) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        try:
            with self._conn() as conn:
                stmt = select(self.snapshots.c.raw_json, self.snapshots.c.fetched_at).order_by(self.snapshots.c.fetched_at.desc()).limit(limit)
                rows = conn.execute(stmt).fetchall()
                for raw, ts in rows:
                    out.append({"data": raw, "fetched_at": ts})
        except Exception:
            pass
        return out

    def get_latest_snapshots(self, n: int = 2) -> List[Dict[str, Any]]:
        return self.list_snapshots(limit=n)

    def _cleanup_old_snapshots(self, conn, keep_recent: int = 100) -> None:
        # Keep only most recent N snapshots
        try:
            # Delete older snapshots not in the newest N
            sql = text("""
                DELETE FROM snapshots
                WHERE id NOT IN (
                    SELECT id FROM snapshots
                    ORDER BY fetched_at DESC
                    LIMIT :keep
                )
            """)
            conn.execute(sql, {"keep": keep_recent})
            conn.commit()
        except Exception:
            pass

    def _save_aircraft_positions(self, conn, data: Dict[str, Any], timestamp: float) -> None:
        aircraft = data.get("pilots") or data.get("aircraft") or []
        try:
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
                        conn.execute(insert(self.aircraft_positions).values(
                            cid=cid, callsign=callsign, timestamp=timestamp,
                            latitude=lat, longitude=lon, altitude=alt,
                            groundspeed=gs, heading=heading
                        ))
                except Exception:
                    continue
            conn.commit()
            # cleanup old positions
            self._cleanup_old_positions(conn)
        except Exception:
            pass

    def _cleanup_old_positions(self, conn) -> None:
        # Keep only the most recent 10 positions per aircraft. Use a window function
        # if supported by the DB. We run raw SQL for portability; Postgres supports
        # the subquery; SQLite 3.25+ supports window functions.
        try:
            sql = text("""
                DELETE FROM aircraft_positions
                WHERE id NOT IN (
                    SELECT id FROM (
                        SELECT id, ROW_NUMBER() OVER (PARTITION BY cid ORDER BY timestamp DESC) as rn
                        FROM aircraft_positions
                    ) t WHERE rn <= 10
                )
            """)
            conn.execute(sql)
            conn.commit()
        except Exception:
            # If window functions aren't available, fallback: keep latest 10 per cid by iterative approach
            try:
                # naive fallback: delete older than timestamp threshold for simplicity (best-effort)
                conn.execute(text("VACUUM"))
            except Exception:
                pass

    def save_incident(self, detected_at: float, callsign: str, cid: Optional[int], lat: float, lon: float, altitude: Optional[float], zone: str, evidence: str) -> int:
        try:
            with self._conn() as conn:
                result = conn.execute(insert(self.incidents).values(
                    detected_at=detected_at, callsign=callsign, cid=cid, lat=lat, lon=lon, altitude=altitude, zone=zone, evidence=evidence
                ))
                conn.commit()
                return int(result.inserted_primary_key[0]) if result.inserted_primary_key else 0
        except Exception:
            return 0

    def update_incident(self, id: int, evidence: str) -> None:
        try:
            with self._conn() as conn:
                conn.execute(text("UPDATE incidents SET evidence = :e WHERE id = :id"), {"e": evidence, "id": id})
                conn.commit()
        except Exception:
            pass

    def get_aircraft_position_history(self, cid: int, limit: int = 10) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        try:
            with self._conn() as conn:
                stmt = select(self.aircraft_positions.c.timestamp, self.aircraft_positions.c.latitude, self.aircraft_positions.c.longitude, self.aircraft_positions.c.altitude, self.aircraft_positions.c.groundspeed, self.aircraft_positions.c.heading).where(self.aircraft_positions.c.cid == cid).order_by(self.aircraft_positions.c.timestamp.desc()).limit(limit)
                rows = conn.execute(stmt).fetchall()
                for ts, lat, lon, alt, gs, hdg in rows:
                    out.append({"timestamp": ts, "latitude": lat, "longitude": lon, "altitude": alt, "groundspeed": gs, "heading": hdg})
        except Exception:
            pass
        return out

    def list_incidents(self, limit: int = 100) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        try:
            with self._conn() as conn:
                stmt = select(self.incidents.c.id, self.incidents.c.detected_at, self.incidents.c.callsign, self.incidents.c.cid, self.incidents.c.lat, self.incidents.c.lon, self.incidents.c.altitude, self.incidents.c.zone, self.incidents.c.evidence).order_by(self.incidents.c.detected_at.desc()).limit(limit)
                rows = conn.execute(stmt).fetchall()
                for row in rows:
                    out.append({
                        "id": row[0],
                        "detected_at": row[1],
                        "callsign": row[2],
                        "cid": row[3],
                        "lat": row[4],
                        "lon": row[5],
                        "altitude": row[6],
                        "zone": row[7],
                        "evidence": row[8],
                    })
        except Exception:
            pass
        return out

    def list_aircraft(self) -> List[Dict[str, Any]]:
        """Return latest aircraft snapshot without embedding per-CID histories.

        This avoids N+1 queries and keeps the endpoint fast. Use
        `/api/v1/aircraft/list/history` for histories.
        """
        snap = self.get_latest_snapshot()
        if not snap:
            return []
        data = snap.get("data")
        if not data:
            return []
        aircraft = data.get("pilots") or data.get("aircraft") or []
        return aircraft

    # classifications helpers
    def save_classification(self, snapshot_id: int, typ: str, summary: Any) -> None:
        try:
            with self._conn() as conn:
                conn.execute(insert(self.classifications).values(snapshot_id=snapshot_id, type=typ, summary_json=summary))
                conn.commit()
        except Exception:
            pass

    def get_latest_classification(self, typ: str) -> Optional[Any]:
        try:
            with self._conn() as conn:
                stmt = select(self.classifications.c.summary_json).where(self.classifications.c.type == typ).order_by(self.classifications.c.id.desc()).limit(1)
                row = conn.execute(stmt).fetchone()
                if not row:
                    return None
                return row[0]
        except Exception:
            return None


# Module-level default STORAGE singleton
try:
    STORAGE = Storage()
except Exception:
    STORAGE = None

__all__ = ["Storage", "STORAGE"]
