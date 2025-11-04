import os
from typing import Any

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

# Create fetcher singleton used by the app. The fetcher will save snapshots to
# storage via a registered callback so other modules can rely on the DB/Storage
# rather than pulling the JSON themselves. The Storage singleton is provided by
# the storage module (STORAGE) and will use its default DB path unless the
# application reinitializes it elsewhere.
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


# Mount API package (routes under /api/v1/...)
app.include_router(api_router)


__all__ = ["app", "STORAGE", "FETCHER"]
