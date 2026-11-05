"""SQLite storage for P-56 intrusion history.

Replaces the single p56_history.json file, which was rewritten in full every
poll cycle and could be lost entirely to one bad write. Here:

- one row per event (keyed by cid + recorded_at, ordered by insertion id) and
  one row per tracked aircraft in ``current_inside``;
- each poll cycle is ONE transaction that only touches rows that changed;
- WAL journaling: a crash or power cut loses at most the last transaction,
  never the history;
- a periodic online backup (``<db>.bak``) for SD-card failure.

The store speaks the same in-memory shape p56_history has always used,
``{"events": [...], "current_inside": {...}}``, so the detection logic did not
have to change. ``load()`` returns a fresh, caller-owned copy; ``save(data)``
diffs it against what is stored.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("vncrcc.p56_store")

BACKUP_INTERVAL_S = 6 * 3600

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    cid         TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    doc         TEXT NOT NULL,
    UNIQUE (cid, recorded_at)
);
CREATE TABLE IF NOT EXISTS current_inside (
    cid TEXT PRIMARY KEY,
    doc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL
);
"""


def event_key(e: Dict[str, Any]) -> Tuple[str, str]:
    """Stable identity of an event. Matches the '<cid>:<recorded_at>' keys the
    frontend and the purge API use (str() of the stored float)."""
    ra = e.get("recorded_at")
    return (str(e.get("cid") or ""), "" if ra is None else str(ra))


def _dumps(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), default=str)


class P56Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        # Serialized docs as last read/written: lets save() skip unchanged rows
        # and lets load() rebuild fresh dicts without touching the disk.
        self._events: Optional[List[Tuple[Tuple[str, str], str]]] = None
        self._current_doc: Optional[str] = None
        self.version = 0  # bumped on every committed change
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    # -- connection -------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    # -- reads --------------------------------------------------------------
    def _ensure_loaded(self) -> None:
        if self._events is not None:
            return
        conn = self._connect()
        try:
            rows = conn.execute("SELECT cid, recorded_at, doc FROM events ORDER BY id").fetchall()
            cur = conn.execute("SELECT cid, doc FROM current_inside").fetchall()
        finally:
            conn.close()
        self._events = [((cid, ra), doc) for cid, ra, doc in rows]
        self._current_doc = _dumps({cid: json.loads(doc) for cid, doc in cur})

    def load(self) -> Dict[str, Any]:
        with self._lock:
            self._ensure_loaded()
            return {
                "events": [json.loads(doc) for _, doc in self._events],
                "current_inside": json.loads(self._current_doc),
            }

    def get_event(self, cid: str, recorded_at: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._ensure_loaded()
            for key, doc in self._events:
                if key == (str(cid), str(recorded_at)):
                    return json.loads(doc)
        return None

    def is_empty(self) -> bool:
        with self._lock:
            self._ensure_loaded()
            return not self._events and self._current_doc in ("{}", None)

    def get_meta(self, k: str) -> Optional[str]:
        conn = self._connect()
        try:
            row = conn.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        finally:
            conn.close()
        return row[0] if row else None

    def set_meta(self, k: str, v: str) -> None:
        conn = self._connect()
        try:
            conn.execute("INSERT INTO meta(k, v) VALUES(?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))
        finally:
            conn.close()

    # -- writes -------------------------------------------------------------
    def save(self, data: Dict[str, Any]) -> int:
        """Persist ``data`` in one transaction, writing only changed rows.
        Returns the number of rows touched."""
        with self._lock:
            self._ensure_loaded()
            old = {key: doc for key, doc in self._events}
            new_list: List[Tuple[Tuple[str, str], str]] = []
            seen = set()
            for e in data.get("events") or []:
                key = event_key(e)
                if key in seen:  # never write two rows for one identity
                    continue
                seen.add(key)
                new_list.append((key, _dumps(e)))
            current_doc = _dumps(data.get("current_inside") or {})

            upserts = [(k, d) for k, d in new_list if old.get(k) != d]
            deletes = [k for k in old if k not in seen]
            current_changed = current_doc != self._current_doc
            if not upserts and not deletes and not current_changed:
                return 0

            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                for (cid, ra), doc in upserts:
                    conn.execute(
                        "INSERT INTO events(cid, recorded_at, doc) VALUES(?,?,?) "
                        "ON CONFLICT(cid, recorded_at) DO UPDATE SET doc=excluded.doc",
                        (cid, ra, doc),
                    )
                for cid, ra in deletes:
                    conn.execute("DELETE FROM events WHERE cid=? AND recorded_at=?", (cid, ra))
                if current_changed:
                    conn.execute("DELETE FROM current_inside")
                    conn.executemany(
                        "INSERT INTO current_inside(cid, doc) VALUES(?, ?)",
                        [(str(c), _dumps(s)) for c, s in (data.get("current_inside") or {}).items()],
                    )
                conn.execute("COMMIT")
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                # Our cache may no longer match the DB; reload on next access.
                self._events = None
                raise
            finally:
                conn.close()

            # Keep the cache in DB order: surviving rows keep their position,
            # new rows are appended (AUTOINCREMENT ids), mirroring ORDER BY id.
            new_map = dict(new_list)
            ordered = [(k, new_map[k]) for k, _ in self._events if k in new_map]
            have = {k for k, _ in ordered}
            ordered += [(k, d) for k, d in new_list if k not in have]
            self._events = ordered
            self._current_doc = current_doc
            self.version += 1
            self._maybe_backup()
            return len(upserts) + len(deletes) + (1 if current_changed else 0)

    def _maybe_backup(self) -> None:
        bak = self.path.with_suffix(self.path.suffix + ".bak")
        try:
            if bak.exists() and time.time() - bak.stat().st_mtime < BACKUP_INTERVAL_S:
                return
            src = self._connect()
            dst = sqlite3.connect(str(bak) + ".tmp")
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            Path(str(bak) + ".tmp").replace(bak)
        except Exception:
            logger.warning("P-56 history DB backup failed", exc_info=True)


_STORES: Dict[str, P56Store] = {}
_STORES_LOCK = threading.Lock()


def get_store(path: Path) -> P56Store:
    key = str(Path(path).resolve())
    with _STORES_LOCK:
        st = _STORES.get(key)
        if st is None:
            st = _STORES[key] = P56Store(Path(path))
        return st
