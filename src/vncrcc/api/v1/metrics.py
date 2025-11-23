from fastapi import APIRouter, Request
from typing import Any, Dict
import time
from ...rate_limit import limiter
from ...metrics import METRICS

router = APIRouter(prefix="/metrics")


@router.get("/")
@limiter.limit("30/minute")
async def get_metrics(request: Request) -> Dict[str, Any]:
    """Get comprehensive system metrics including delay monitoring, active users, and resource usage.

    Returns:
        - timestamp: Current server time
        - uptime_seconds: Server uptime
        - active_users: Count of unique IPs in last 5 minutes
        - request_rate: Requests per second (1min and 5min windows)
        - error_rate: Errors per second (1min and 5min windows)
        - delay: VATSIM data staleness statistics and history for graphing
        - resources: CPU, memory, disk, network usage
        - endpoints: Per-endpoint request/error counts
        - p56_purges: Recent P56 history purge operations
    """
    return METRICS.get_summary()


@router.get("/delay")
@limiter.limit("30/minute")
async def get_delay_metrics(request: Request) -> Dict[str, Any]:
    """Get detailed delay/staleness metrics for VATSIM data.

    Returns delay statistics (avg, min, max, p50, p95) for 1min and 5min windows,
    plus time-series history data suitable for line graph visualization.
    """
    return {
        "1min": METRICS.get_delay_stats(window=60),
        "5min": METRICS.get_delay_stats(window=300),
        "history": METRICS.get_delay_history(limit=100),
    }


@router.get("/vatsim-health")
@limiter.limit("30/minute")
async def get_vatsim_health(request: Request) -> Dict[str, Any]:
    """Diagnostic endpoint for VATSIM data pipeline health.

    Returns information about the VATSIM fetch loop status, including:
    - last_fetch_ts: When we last successfully fetched from VATSIM
    - vatsim_data_age: How old the VATSIM data itself is (staleness)
    - time_since_last_fetch: How long since our last fetch attempt
    - fetcher_status: Whether the fetch loop appears to be running
    """
    from ...app import FETCHER
    from ...storage import STORAGE

    now = time.time()
    health = {
        "server_time": now,
        "fetcher_running": FETCHER._task is not None if FETCHER else False,
        "last_fetch_ts": None,
        "vatsim_data_age": None,
        "time_since_last_fetch": None,
        "fetcher_status": "unknown",
    }

    if FETCHER:
        health["last_fetch_ts"] = FETCHER.latest_ts
        health["vatsim_data_age"] = FETCHER.latest_delay

        if FETCHER.latest_ts:
            time_since_fetch = now - FETCHER.latest_ts
            health["time_since_last_fetch"] = round(time_since_fetch, 1)

            # Determine fetcher health status
            if time_since_fetch > 60:
                health["fetcher_status"] = "stale"
                health["warning"] = f"No fetch in {time_since_fetch:.0f}s (expected every 15s)"
            elif time_since_fetch > 30:
                health["fetcher_status"] = "slow"
            else:
                health["fetcher_status"] = "healthy"

    # Check storage for additional context
    if STORAGE:
        latest_snap = STORAGE.get_latest_snapshot()
        if latest_snap:
            snap_ts = latest_snap.get("fetched_at")
            if snap_ts:
                health["latest_snapshot_ts"] = snap_ts
                health["time_since_snapshot"] = round(now - snap_ts, 1)

    return health
