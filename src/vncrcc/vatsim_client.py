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
        self.latest_delay: Optional[float] = None  # VATSIM data age/staleness
        self._callbacks: List[Callable[[Dict[str, Any], float], None]] = []
        self._task: Optional[asyncio.Task] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._lock = asyncio.Lock()

        # Adaptive timing: sync with VATSIM update cycle
        self._vatsim_update_ts: Optional[float] = None  # Last known VATSIM update timestamp
        self._sync_offset: float = 1.0  # Target offset after VATSIM update (1 second to allow propagation)
        self._resync_counter: int = 0  # Counter to trigger periodic resync

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
            # Force IPv4 to avoid IPv6 routing issues; increase timeout
            connector = aiohttp.TCPConnector(ssl=ssl_ctx, family=2)  # AF_INET = IPv4
        except Exception:
            connector = None
        # create session with connector (if connector is None, ClientSession will pick defaults)
        timeout = aiohttp.ClientTimeout(total=60, connect=30)
        self._session = aiohttp.ClientSession(connector=connector, timeout=timeout)
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
            except asyncio.TimeoutError:
                logger.error("VATSIM fetch timeout after 60s connecting to %s", self.base_url)
            except aiohttp.ClientError as exc:
                logger.error("VATSIM fetch client error: %s: %s", type(exc).__name__, exc)
            except Exception as exc:
                logger.exception("VATSIM fetch error: %s", exc)

            # Adaptive sleep: sync with VATSIM update cycle
            sleep_duration = self._calculate_adaptive_sleep()
            await asyncio.sleep(sleep_duration)

    async def _fetch_once(self) -> None:
        if not self._session:
            timeout = aiohttp.ClientTimeout(total=60, connect=30)
            self._session = aiohttp.ClientSession(timeout=timeout)
        # use base_url as the default fetch target
        fetch_start = time.time()
        async with self._session.get(self.base_url) as resp:
            if resp.status != 200:
                raise RuntimeError(f"VATSIM fetch returned status {resp.status}")
            data = await resp.json()
            ts = time.time()
            fetch_duration = ts - fetch_start
            
            # Extract VATSIM's update timestamp to measure staleness
            vatsim_update_ts = None
            vatsim_age_seconds = None
            try:
                general = data.get("general", {})
                update_str = general.get("update_timestamp") or general.get("update")
                if update_str:
                    # Parse ISO or compact format
                    from datetime import datetime
                    if 'T' in update_str or '-' in update_str:
                        vatsim_dt = datetime.fromisoformat(update_str.replace('Z', '+00:00'))
                    else:
                        # Compact: "20251120211931"
                        y, m, d, h, mi, s = update_str[:4], update_str[4:6], update_str[6:8], update_str[8:10], update_str[10:12], update_str[12:14]
                        vatsim_dt = datetime.strptime(f"{y}-{m}-{d}T{h}:{mi}:{s}Z", "%Y-%m-%dT%H:%M:%SZ")
                    vatsim_update_ts = vatsim_dt.timestamp()
                    vatsim_age_seconds = ts - vatsim_update_ts
            except Exception:
                pass
            
            # Count aircraft/pilots for log visibility
            count = len((data.get("pilots") or data.get("aircraft") or []))
            async with self._lock:
                self.latest = data
                self.latest_ts = ts
                self.latest_delay = vatsim_age_seconds
                # Track VATSIM update timestamp for adaptive timing
                if vatsim_update_ts is not None:
                    self._vatsim_update_ts = vatsim_update_ts

            # Log with staleness info
            if vatsim_age_seconds is not None:
                logger.info("VATSIM fetch success: %d aircraft, fetch took %.2fs, data age %.1fs",
                           count, fetch_duration, vatsim_age_seconds)
            else:
                logger.info("VATSIM fetch success: %d aircraft at %.0f, fetch took %.2fs",
                           count, ts, fetch_duration)

            # Record delay to metrics if available
            if vatsim_age_seconds is not None:
                try:
                    from .metrics import METRICS
                    METRICS.record_delay(vatsim_age_seconds, source="vatsim")
                except Exception:
                    pass  # Don't let metrics recording fail the fetch

            # call registered callbacks (run them sync to keep ordering)
            callback_start = time.time()
            for cb in list(self._callbacks):
                try:
                    cb(data, ts)
                except Exception as e:
                    logger.exception("VATSIM callback error: %s", e)
            callback_duration = time.time() - callback_start
            if callback_duration > 1.0:
                logger.warning("VATSIM callbacks took %.2fs (slow!)", callback_duration)

    def _calculate_adaptive_sleep(self) -> float:
        """Calculate adaptive sleep duration to sync with VATSIM update cycle.

        Strategy:
        - VATSIM updates every 15 seconds
        - We want to fetch ~1 second after their update for fresh data
        - Gradually adjust offset to avoid always hitting same part of cycle
        - Resync every 20 fetches to correct drift

        Returns:
            Sleep duration in seconds
        """
        # Increment resync counter
        self._resync_counter += 1

        # If we don't know VATSIM's update timestamp yet, use default interval
        if self._vatsim_update_ts is None:
            return self.interval

        now = time.time()
        time_since_vatsim_update = now - self._vatsim_update_ts

        # Calculate when the next VATSIM update is expected (every 15 seconds)
        # VATSIM updates at: vatsim_update_ts + 0, +15, +30, +45, ...
        seconds_into_cycle = time_since_vatsim_update % 15
        seconds_until_next_update = 15 - seconds_into_cycle

        # Target: fetch 1 second after VATSIM update
        # Gradually vary offset between 0.5s and 2.5s to avoid always hitting same point
        # This prevents getting stuck at the tail end of an update cycle
        if self._resync_counter >= 20:
            # Every 20 fetches, vary the offset slightly (0.5s to 2.5s)
            # Use modulo pattern to cycle through different offsets
            offset_variation = (self._resync_counter % 5) * 0.5
            self._sync_offset = 0.5 + offset_variation
            self._resync_counter = 0
            logger.info(f"Adaptive timing: adjusting sync offset to {self._sync_offset:.1f}s")

        target_sleep = seconds_until_next_update + self._sync_offset

        # Clamp to reasonable bounds (don't sleep less than 5s or more than 20s)
        target_sleep = max(5.0, min(20.0, target_sleep))

        logger.debug(f"Adaptive sleep: {target_sleep:.1f}s (cycle position: {seconds_into_cycle:.1f}s, "
                    f"offset: {self._sync_offset:.1f}s)")

        return target_sleep

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
