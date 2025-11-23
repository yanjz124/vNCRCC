from fastapi import APIRouter, Request
from typing import Any, Dict
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
