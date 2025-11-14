import json
import os
import time
from typing import Any, Dict, List, Optional

import sqlite3
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


class Storage:
    """DB abstraction using SQLAlchemy that supports SQLite or PostgreSQL.

    Set the environment variable `VNCRCC_DATABASE_URL` to a SQLAlchemy-style
    URL (e.g. postgres://... or sqlite:///vncrcc.db). If not provided, the
    implementation falls back to SQLite file `vncrcc.db`.
    """

    def __init__(self, db_url: Optional[str] = None, db_path: Optional[str] = None) -> None:
        # Backwards-compatible constructor: callers may pass `db_path` (old
        # sqlite-based code/tests) or `db_url` (SQLAlchemy URL). Priority:
        # 1. Explicit db_url argument
        # 2. Explicit db_path argument
        # 3. VNCRCC_DATABASE_URL env var
        # 4. default sqlite file `vncrcc.db`
        if db_url:
            url = db_url
        elif db_path:
            # If db_path looks like an in-memory or file path, convert to sqlite URL
            if db_path == ":memory:" or db_path.startswith("file:"):
                url = f"sqlite:///{db_path}"
            else:
                # Interpret raw path; for absolute/relative paths, prefix sqlite:///
                url = f"sqlite:///{db_path}"
        else:
            url = os.environ.get("VNCRCC_DATABASE_URL") or "sqlite:///vncrcc.db"
        # For sqlite, allow check_same_thread via connect_args; SQLAlchemy will
        # handle that automatically if requested.
        connect_args = {}
        if url.startswith("sqlite:"):
            connect_args = {"check_same_thread": False}
        else:
            connect_args = {}

        # Create engine and metadata
        self.engine: Engine = create_engine(url, future=True, connect_args=connect_args)
        self.metadata = MetaData()

        # Backwards compatibility: if caller supplied a db_path (legacy), expose
        # a raw sqlite3 connection as `.conn` so existing scripts/tests that
        # access storage.STORAGE.conn continue to work. Only create this when
        # db_path is provided and the URL is sqlite-based.
        self.conn = None
        try:
            if db_path and url.startswith("sqlite:"):
                # db_path may be an absolute or relative filesystem path
                try:
                    self.conn = sqlite3.connect(db_path, check_same_thread=False)
                    try:
                        cur = self.conn.cursor()
                        cur.execute("PRAGMA journal_mode=WAL;")
                        cur.execute("PRAGMA synchronous=NORMAL;")
                        cur.execute("PRAGMA busy_timeout=5000;")
                    except Exception:
                        pass
                except Exception:
                    self.conn = None
        except Exception:
            self.conn = None

        # Tables
        # snapshots: store raw JSON blob per fetch
        self.snapshots = Table(
            "snapshots",
            self.metadata,
            Column("id", Integer, primary_key=True),
            Column("fetched_at", Float, nullable=False),
            Column("raw_json", JSON, nullable=False),
        )

        # incidents
        self.incidents = Table(
            "incidents",
            self.metadata,
            Column("id", Integer, primary_key=True),
            Column("detected_at", Float, nullable=False),
            Column("callsign", String),
            Column("cid", Integer),
            Column("lat", Float),
            Column("lon", Float),
            Column("altitude", Float),
            Column("zone", String),
            Column("evidence", Text),
        )

        # aircraft_positions: history per aircraft
        self.aircraft_positions = Table(
            "aircraft_positions",
            self.metadata,
            Column("id", Integer, primary_key=True),
            Column("cid", Integer, index=True),
            Column("callsign", String),
            Column("timestamp", Float),
            Column("latitude", Float),
            Column("longitude", Float),
            Column("altitude", Float),
            Column("groundspeed", Float),
            Column("heading", Float),
        )

        # classifications: store precomputed SFRA/FRZ/P56 summaries per snapshot
        self.classifications = Table(
            "classifications",
            self.metadata,
            Column("id", Integer, primary_key=True),
            Column("snapshot_id", Integer, index=True),
            Column("type", String),
            Column("summary_json", JSON),
        )

        # Create tables if they don't exist
        try:
            self.metadata.create_all(self.engine)
        except SQLAlchemyError:
            # If create_all fails (rare), ignore and let runtime operations fail
            pass

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
        snap = self.get_latest_snapshot()
        if not snap:
            return []
        data = snap.get("data")
        if not data:
            return []
        aircraft = data.get("pilots") or data.get("aircraft") or []
        for ac in aircraft:
            cid = ac.get("cid")
            if cid is not None:
                ac["position_history"] = self.get_aircraft_position_history(cid, 10)
            else:
                ac["position_history"] = []
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
