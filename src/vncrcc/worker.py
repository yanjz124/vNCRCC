"""Small runner that starts the fetcher and keeps the process alive.

This file is useful for development or running the fetch/save loop without
starting the web server. It registers a callback that prints counts to stdout.
"""

import asyncio
import os
import logging
import yaml
from .vatsim_client import VatsimClient
from .storage import Storage

logger = logging.getLogger("vncrcc.worker")


async def main() -> None:
    cfg_path = os.environ.get("VNCRCC_CONFIG", "config/example_config.yaml")
    cfg = yaml.safe_load(open(cfg_path)) if os.path.exists(cfg_path := cfg_path) else {}
    db_path = cfg.get("db_path", "vncrcc.db")
    storage = Storage(db_path)
    fetcher = VatsimClient(cfg.get("vatsim_url", "https://data.vatsim.net/v3/vatsim-data.json"), cfg.get("poll_interval", 15))

    def cb(data, ts):
        sid = storage.save_snapshot(data, ts)
        count = len((data.get("pilots") or data.get("aircraft") or []))
        logger.info("Saved snapshot %s with %d aircraft at %s", sid, count, ts)

    fetcher.register_callback(cb)
    await fetcher.start()
    try:
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        await fetcher.stop()


if __name__ == "__main__":
    asyncio.run(main())
