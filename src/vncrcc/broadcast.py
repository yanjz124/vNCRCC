"""Server-Sent Events broadcaster for real-time data push.

Uses asyncio.Condition for zero-CPU wait. All SSE clients share one
Condition and are woken simultaneously when new data arrives.
The payload is serialized once and shared across all subscribers.
"""
import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator, Dict, Optional

logger = logging.getLogger("vncrcc.broadcast")


class DataBroadcaster:
    """Manages SSE subscriptions and broadcasts dashboard payloads."""

    def __init__(self) -> None:
        self._condition: Optional[asyncio.Condition] = None
        self._latest_payload: Optional[str] = None
        self._latest_ts: float = 0
        self._subscriber_count: int = 0
        self._total_broadcasts: int = 0
        # Monotonic version of _latest_payload. Subscribers compare against
        # this rather than wall-clock time: a backwards clock step (NTP) made
        # `_latest_ts > last_seen_ts` false and froze every open stream.
        self._seq: int = 0

    def _ensure_condition(self) -> asyncio.Condition:
        if self._condition is None:
            self._condition = asyncio.Condition()
        return self._condition

    async def notify(self, payload_dict: Dict[str, Any]) -> None:
        """Broadcast a new payload to all waiting SSE clients."""
        try:
            serialized = json.dumps(payload_dict, separators=(',', ':'), default=str)
        except Exception:
            logger.exception("Failed to serialize broadcast payload")
            return

        condition = self._ensure_condition()
        async with condition:
            self._latest_payload = serialized
            self._latest_ts = time.time()
            self._total_broadcasts += 1
            self._seq += 1
            condition.notify_all()

        if self._subscriber_count > 0:
            logger.debug("Broadcast to %d subscribers (%d bytes)",
                         self._subscriber_count, len(serialized))

    async def subscribe(self) -> AsyncGenerator[str, None]:
        """Async generator yielding SSE-formatted messages."""
        condition = self._ensure_condition()
        self._subscriber_count += 1
        last_seen = 0

        try:
            # Send latest data immediately on connect
            if self._latest_payload and self._seq > last_seen:
                last_seen = self._seq
                yield f"event: update\ndata: {self._latest_payload}\n\n"

            while True:
                # Only hold the condition lock while waiting/reading state.
                # Yielding while holding it would let one slow client (whose
                # socket send is blocked) stall notify() and every other
                # subscriber until that client drains.
                message: Optional[str] = None
                async with condition:
                    try:
                        await asyncio.wait_for(
                            condition.wait_for(lambda: self._seq > last_seen),
                            timeout=15.0
                        )
                    except asyncio.TimeoutError:
                        pass
                    if self._latest_payload and self._seq > last_seen:
                        last_seen = self._seq
                        message = f"event: update\ndata: {self._latest_payload}\n\n"

                if message is None:
                    yield f": heartbeat {int(time.time())}\n\n"
                else:
                    yield message
        finally:
            self._subscriber_count -= 1

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "active_subscribers": self._subscriber_count,
            "total_broadcasts": self._total_broadcasts,
            "latest_ts": self._latest_ts,
        }


BROADCASTER = DataBroadcaster()
