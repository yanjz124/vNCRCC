import os
import logging
from typing import Any
from datetime import datetime

import yaml
from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import FileResponse
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.staticfiles import StaticFiles

from .storage import STORAGE
from .aircraft_history import update_history_batch
from .vatsim_client import VatsimClient
from .api import router as api_router
from .precompute import precompute_all
import asyncio


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


_WRITE_JSON_HISTORY = os.getenv("VNCRCC_WRITE_JSON_HISTORY", "0").strip() == "1"
_TRACK_POSITIONS = os.getenv("VNCRCC_TRACK_POSITIONS", "0").strip() == "1"


def _on_fetch(data: dict, ts: float) -> None:
    try:
        sid = STORAGE.save_snapshot(data, ts)
        aircraft = (data.get("pilots") or data.get("aircraft") or [])
        count = len(aircraft)
        timestamp_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        logger.info("Saved snapshot %s with %d aircraft at %s", sid, count, timestamp_str)

        # Offload heavy work to background threads to avoid blocking the event loop
        async def _bg():
            loop = asyncio.get_running_loop()
            tasks = []
            if _WRITE_JSON_HISTORY:
                # Only track history for aircraft in the filtered/cached list (within range)
                from .precompute import get_cached
                cached = get_cached("aircraft_list")
                filtered_aircraft = cached.get("aircraft", []) if cached else []
                
                # Build set of CIDs that are in the filtered list
                filtered_cids = set()
                history_updates = {}
                for ac in filtered_aircraft:
                    try:
                        cid = str(ac.get("cid") or ac.get("callsign") or "").strip()
                        if not cid:
                            continue
                        filtered_cids.add(cid)
                        lat = ac.get("latitude") or ac.get("lat") or ac.get("y")
                        lon = ac.get("longitude") or ac.get("lon") or ac.get("x")
                        alt = ac.get("altitude") or ac.get("alt")
                        if lat is None or lon is None:
                            continue
                        history_updates[cid] = {
                            "lat": lat, 
                            "lon": lon, 
                            "alt": alt, 
                            "callsign": ac.get("callsign", ""),
                            "gs": ac.get("groundspeed"),
                            "heading": ac.get("heading")
                        }
                    except Exception:
                        continue
                if history_updates:
                    # Update history FIRST, then precompute can read from it
                    await loop.run_in_executor(None, update_history_batch, history_updates, filtered_cids)
            # Precompute in thread (runs after history is updated)
            try:
                await loop.run_in_executor(None, precompute_all, data, ts)
            except Exception:
                logger.exception("Background tasks failed")

        try:
            asyncio.get_running_loop().create_task(_bg())
        except Exception:
            # if not in an event loop (unlikely), run synchronously as last resort
            try:
                precompute_all(data, ts)
            except Exception:
                logger.exception("Precompute failed (sync fallback)")
    except Exception:
        logger.exception("Error during fetch callback (_on_fetch)")


class NoCacheMiddleware(BaseHTTPMiddleware):
    """Prevent caching of HTML files to ensure fresh deploys are immediately visible."""
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        # Don't cache HTML files or root path to ensure users always get latest UI
        if request.url.path == "/" or request.url.path.endswith(".html"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


app.add_middleware(NoCacheMiddleware)


@app.on_event("startup")
async def startup() -> None:
    # configure basic logging for development
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    logger.info("VNCRCC_WRITE_JSON_HISTORY=%s VNCRCC_TRACK_POSITIONS=%s", _WRITE_JSON_HISTORY, _TRACK_POSITIONS)
    FETCHER.register_callback(_on_fetch)
    await FETCHER.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    await FETCHER.stop()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/version")
async def version() -> dict:
    """Return the current git commit and timestamp to verify deployment."""
    import subprocess
    try:
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=BASE_DIR).decode().strip()
        timestamp_str = subprocess.check_output(["git", "log", "-1", "--format=%ct"], cwd=BASE_DIR).decode().strip()
        timestamp = int(timestamp_str) if timestamp_str else None
        return {"version": commit, "timestamp": timestamp, "status": "deployed"}
    except Exception:
        return {"version": "unknown", "timestamp": None, "status": "error"}


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
