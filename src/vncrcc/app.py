import os
import logging
from typing import Any
from datetime import datetime

import yaml
from fastapi import FastAPI

from .storage import STORAGE
from .vatsim_client import VatsimClient
from .api import router as api_router


def _load_config(path: str) -> Any:
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


CONFIG_PATH = os.environ.get("VNCRCC_CONFIG", "config/example_config.yaml")
CFG = _load_config(CONFIG_PATH)


app = FastAPI(title="vNCRCC API")

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
        # Log a small debug line so devs can see fetches in the server logs
        count = len((data.get("pilots") or data.get("aircraft") or []))
        timestamp_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        logger.info("Saved snapshot %s with %d aircraft at %s", sid, count, timestamp_str)
    except Exception as e:
        logger.exception("Error saving snapshot")


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


__all__ = ["app", "STORAGE", "FETCHER"]
