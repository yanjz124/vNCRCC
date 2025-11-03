import os
from typing import Any

import yaml
from fastapi import FastAPI

from .storage import Storage
from .vatsim_client import VatsimClient


def _load_config(path: str) -> Any:
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


CONFIG_PATH = os.environ.get("VNCRCC_CONFIG", "config/example_config.yaml")
CFG = _load_config(CONFIG_PATH)


app = FastAPI(title="vNCRCC API")

# Create storage and fetcher singletons used by the app. The fetcher will
# save snapshots to storage via a registered callback so other modules can
# rely on the DB/Storage rather than pulling the JSON themselves.
STORAGE = Storage(CFG.get("db_path", "vncrcc.db"))
FETCHER = VatsimClient(CFG.get("vatsim_url", "https://data.vatsim.net/v3/vatsim-data.json"), CFG.get("poll_interval", 15))


def _on_fetch(data: dict, ts: float) -> None:
    try:
        STORAGE.save_snapshot(data, ts)
    except Exception as e:
        print("Error saving snapshot:", e)


@app.on_event("startup")
async def startup() -> None:
    FETCHER.register_callback(_on_fetch)
    await FETCHER.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    await FETCHER.stop()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/aircraft")
async def aircraft() -> dict:
    return {"aircraft": STORAGE.list_aircraft()}


@app.get("/incidents")
async def incidents(limit: int = 100) -> list:
    cur = STORAGE.conn.cursor()
    cur.execute("SELECT id, detected_at, callsign, cid, lat, lon, altitude, zone, evidence FROM incidents ORDER BY detected_at DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    cols = ["id", "detected_at", "callsign", "cid", "lat", "lon", "altitude", "zone", "evidence"]
    return [dict(zip(cols, r)) for r in rows]


__all__ = ["app", "STORAGE", "FETCHER"]
