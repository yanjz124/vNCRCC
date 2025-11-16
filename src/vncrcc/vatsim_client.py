import asyncio
import time
from contextlib import suppress
from typing import Any, Callable, Dict, List, Optional, Tuple

import aiohttp
import ssl
import os
import logging
try:
    import certifi
except Exception:  # pragma: no cover - optional dependency
    certifi = None

logger = logging.getLogger("vncrcc.vatsim")


class VatsimClient:
    """Asynchronous VATSIM client and poller.

    Design goals:
    - Provide a single shared fetcher for the application.
    - Be flexible for future VATSIM endpoints (not just the single JSON file).
    - Keep a simple callback model so other modules can subscribe to new data.
    """

    def __init__(self, url: str, interval: int = 15):
        """Create the client.

        Args:
            url: Default URL to fetch (can be a full resource URL).
            interval: Poll interval in seconds when using start().
        """
        # `base_url` here may be a full resource URL (for backward compat),
        # but callers can use `fetch_url`/`fetch_resource` to request other
        # endpoints in the future.
        self.base_url = url
        self.interval = interval
        self.latest: Optional[Dict[str, Any]] = None
        self.latest_ts: Optional[float] = None
        self._callbacks: List[Callable[[Dict[str, Any], float], None]] = []
        self._task: Optional[asyncio.Task] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._lock = asyncio.Lock()

    def register_callback(self, cb: Callable[[Dict[str, Any], float], None]) -> None:
        """Register a synchronous callback that will be run after each successful fetch.

        Callbacks are executed synchronously in the fetch loop. Keep them fast.
        """
        self._callbacks.append(cb)

    # Backwards-compatible name for existing code
    # (existing imports that expect VatsimDataFetcher will still work)
    # VatsimDataFetcher = VatsimClient  <-- alias provided at module bottom

    async def start(self) -> None:
        if self._task:
            return
        # ensure Python uses certifi's CA bundle when available (helps macOS Python installs)
        try:
            if certifi:
                os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        except Exception:
            pass

        # create an SSL context that uses certifi's CA bundle when available
        try:
            if certifi:
                ssl_ctx = ssl.create_default_context(cafile=certifi.where())
            else:
                ssl_ctx = ssl.create_default_context()
            connector = aiohttp.TCPConnector(ssl=ssl_ctx)
        except Exception:
            connector = None
        # create session with connector (if connector is None, ClientSession will pick defaults)
        self._session = aiohttp.ClientSession(connector=connector)
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._session:
            await self._session.close()
            self._session = None

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self._fetch_once()
            except Exception as exc:  # keep loop alive on errors
                logger.error("VATSIM fetch error: %s", exc)
            await asyncio.sleep(self.interval)

    async def _fetch_once(self) -> None:
        if not self._session:
            self._session = aiohttp.ClientSession()
        # use base_url as the default fetch target
        async with self._session.get(self.base_url, timeout=30) as resp:
            if resp.status != 200:
                raise RuntimeError(f"VATSIM fetch returned status {resp.status}")
            data = await resp.json()
            ts = time.time()
            # Count aircraft/pilots for log visibility
            count = len((data.get("pilots") or data.get("aircraft") or []))
            async with self._lock:
                self.latest = data
                self.latest_ts = ts
            logger.info("VATSIM fetch success: %d aircraft at %.0f", count, ts)
            # call registered callbacks (run them sync to keep ordering)
            for cb in list(self._callbacks):
                try:
                    cb(data, ts)
                except Exception as e:
                    logger.exception("VATSIM callback error: %s", e)

    async def fetch_url(self, url: str) -> Tuple[Optional[Dict[str, Any]], Optional[float]]:
        """Fetch an arbitrary URL once and return (data, ts).

        This is useful to fetch other VATSIM endpoints without starting the
        poll loop. It does not update the client's `latest` cache.
        """
        if not self._session:
            self._session = aiohttp.ClientSession()
        async with self._session.get(url, timeout=30) as resp:
            if resp.status != 200:
                raise RuntimeError(f"fetch_url returned status {resp.status}")
            data = await resp.json()
            return data, time.time()

    async def fetch_resource(self, resource_path: str) -> Tuple[Optional[Dict[str, Any]], Optional[float]]:
        """Fetch a resource relative to the base URL when possible.

        If `base_url` is a full URL (contains a resource), this will try to
        intelligently join paths. For now it simply treats `resource_path`
        as a full URL if it starts with http(s)://, otherwise attempts a
        simple concatenation.
        """
        if resource_path.startswith("http://") or resource_path.startswith("https://"):
            return await self.fetch_url(resource_path)
        # naive join: if base_url ends with '/', concatenate; otherwise insert '/'
        if self.base_url.endswith("/"):
            url = self.base_url + resource_path
        else:
            url = self.base_url + "/" + resource_path
        return await self.fetch_url(url)

    async def get_latest(self, wait: bool = True, timeout: float = 5.0) -> Tuple[Optional[Dict[str, Any]], Optional[float]]:
        """Return the latest JSON payload and timestamp.

        If no payload is available and wait=True, wait up to `timeout` seconds
        for the first successful fetch.
        """
        if self.latest is not None:
            return self.latest, self.latest_ts
        if not wait:
            return None, None
        waited = 0.0
        interval = 0.5
        while waited < timeout:
            await asyncio.sleep(interval)
            waited += interval
            if self.latest is not None:
                return self.latest, self.latest_ts
        return None, None


# Backwards-compatible alias for older imports
VatsimDataFetcher = VatsimClient

__all__ = ["VatsimClient", "VatsimDataFetcher"]
