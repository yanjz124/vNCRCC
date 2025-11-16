import os
import logging
from typing import Any
from datetime import datetime

import yaml
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.staticfiles import StaticFiles

from .storage import STORAGE
from .aircraft_history import update_history_batch
from .vatsim_client import VatsimClient
from .api import router as api_router
from .precompute import precompute_all


def _load_config(path: str) -> Any:
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


CONFIG_PATH = os.environ.get("VNCRCC_CONFIG", "config/example_config.yaml")
CFG = _load_config(CONFIG_PATH)

# Base directory of the project (repo root). Use this to reliably locate the
# `web` static files regardless of current working directory when the app runs.
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


app = FastAPI(title="vNCRCC API")

# Middleware to disable caching for all responses
class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

app.add_middleware(NoCacheMiddleware)

# module logger
logger = logging.getLogger("vncrcc")


# Create fetcher singleton used by the app. The fetcher will save snapshots to
# storage via a registered callback so other modules can rely on the DB/Storage
# rather than pulling the JSON themselves. The Storage singleton is provided by
# the storage module (STORAGE) and will use its default DB path unless the
# application reinitializes it elsewhere.
FETCHER = VatsimClient(CFG.get("vatsim_url", "https://data.vatsim.net/v3/vatsim-data.json"), CFG.get("poll_interval", 15))


def _on_fetch(data: dict, ts: float) -> None:
    try:
        sid = STORAGE.save_snapshot(data, ts)
        aircraft = (data.get("pilots") or data.get("aircraft") or [])
        count = len(aircraft)
        timestamp_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        logger.info("Saved snapshot %s with %d aircraft at %s", sid, count, timestamp_str)

        # Batch update aircraft history (lightweight: keeps last 10 positions per CID)
        history_updates = {}
        for ac in aircraft:
            cid = str(ac.get("cid") or ac.get("callsign") or "").strip()
            if not cid:
                continue
            lat = ac.get("latitude") or ac.get("lat") or ac.get("y")
            lon = ac.get("longitude") or ac.get("lon") or ac.get("x")
            alt = ac.get("altitude") or ac.get("alt")
            if lat is None or lon is None:
                continue
            history_updates[cid] = {"lat": lat, "lon": lon, "alt": alt, "callsign": ac.get("callsign", "")}
        if history_updates:
            update_history_batch(history_updates)
        
        # Pre-compute all geofence checks and analytics so user requests are instant
        precompute_all(data, ts)
    except Exception:
        logger.exception("Error during fetch callback (_on_fetch)")


@app.on_event("startup")
async def startup() -> None:
    # configure basic logging for development
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    FETCHER.register_callback(_on_fetch)
    await FETCHER.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    await FETCHER.stop()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/debug/last_snapshot")
async def last_snapshot() -> dict:
    """Return the timestamp and aircraft count of the latest saved snapshot.

    This is a small debug endpoint useful to verify the fetch loop is saving
    snapshots at the expected interval.
    """
    snap = STORAGE.get_latest_snapshot() if STORAGE else None
    if not snap:
        return {"last_snapshot": None}
    data = snap.get("data", {})
    ts = snap.get("fetched_at")
    count = len((data.get("pilots") or data.get("aircraft") or []))
    return {"fetched_at": ts, "aircraft_count": count}


# Mount API package (routes under /api/v1/...)
app.include_router(api_router)


# Serve the entire `web` directory at root so requests like /app.js and
# /styles.css return the actual files. We mount the API router first so
# routes under /api/* take precedence.
try:
    web_dir = os.path.join(BASE_DIR, "web")
    app.mount("/", StaticFiles(directory=web_dir, html=True), name="webroot")
except Exception:
    logger.exception("Failed to mount web static directory at /")


__all__ = ["app", "STORAGE", "FETCHER"]
