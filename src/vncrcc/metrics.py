"""Metrics tracking for monitoring active users and resource usage."""
import time
import psutil
from collections import defaultdict, deque
from datetime import datetime
from typing import Dict, Optional


class MetricsTracker:
    """Track API metrics, active users, and resource usage."""
    
    def __init__(self, active_window: int = 300):
        """
        Args:
            active_window: Time window in seconds to consider a user active (default 5 min)
        """
        self.active_window = active_window

        # Track requests: {endpoint: deque of (timestamp, ip)}
        self._requests: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))

        # Track errors: {endpoint: deque of (timestamp, error_type)}
        self._errors: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))

        # Track unique IPs: {ip: last_seen_timestamp}
        self._active_ips: Dict[str, float] = {}

        # Track P56 purge operations: deque of (timestamp, count, client_ip)
        self._p56_purges: deque = deque(maxlen=100)

        # Track VATSIM data delays: deque of (timestamp, delay_seconds, source)
        self._delays: deque = deque(maxlen=1000)

        # Process start time
        self._start_time = time.time()
    
    def record_request(self, endpoint: str, client_ip: str) -> None:
        """Record a request from a client IP to an endpoint."""
        now = time.time()
        self._requests[endpoint].append((now, client_ip))
        self._active_ips[client_ip] = now
    
    def record_error(self, endpoint: str, error_type: str) -> None:
        """Record an error for an endpoint."""
        now = time.time()
        self._errors[endpoint].append((now, error_type))
    
    def record_p56_purge(self, count: int, client_ip: str) -> None:
        """Record a P56 purge operation."""
        now = time.time()
        self._p56_purges.append((now, count, client_ip))

    def record_delay(self, delay_seconds: float, source: str = "vatsim") -> None:
        """Record a data delay/staleness measurement (e.g., VATSIM data age).

        Args:
            delay_seconds: Age of the data in seconds (staleness)
            source: Source identifier (e.g., "vatsim", "vnas")
        """
        now = time.time()
        self._delays.append((now, delay_seconds, source))
    
    def get_active_users(self) -> int:
        """Get count of unique IPs active in the last window."""
        cutoff = time.time() - self.active_window
        # Clean up old IPs
        self._active_ips = {ip: ts for ip, ts in self._active_ips.items() if ts > cutoff}
        return len(self._active_ips)
    
    def get_request_rate(self, endpoint: Optional[str] = None, window: int = 60) -> float:
        """Get requests per second for an endpoint (or all) in the last window."""
        cutoff = time.time() - window
        
        if endpoint:
            requests = self._requests.get(endpoint, deque())
            count = sum(1 for ts, _ in requests if ts > cutoff)
        else:
            count = sum(
                sum(1 for ts, _ in reqs if ts > cutoff)
                for reqs in self._requests.values()
            )
        
        return count / window if window > 0 else 0
    
    def get_error_rate(self, endpoint: Optional[str] = None, window: int = 60) -> float:
        """Get errors per second for an endpoint (or all) in the last window."""
        cutoff = time.time() - window
        
        if endpoint:
            errors = self._errors.get(endpoint, deque())
            count = sum(1 for ts, _ in errors if ts > cutoff)
        else:
            count = sum(
                sum(1 for ts, _ in errs if ts > cutoff)
                for errs in self._errors.values()
            )
        
        return count / window if window > 0 else 0
    
    def get_resource_usage(self) -> dict:
        """Get current system resource usage."""
        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            # Network I/O
            net = psutil.net_io_counters()
            
            return {
                "cpu_percent": round(cpu_percent, 1),
                "memory": {
                    "used_mb": round(memory.used / 1024 / 1024, 1),
                    "available_mb": round(memory.available / 1024 / 1024, 1),
                    "percent": round(memory.percent, 1),
                },
                "disk": {
                    "used_gb": round(disk.used / 1024 / 1024 / 1024, 1),
                    "free_gb": round(disk.free / 1024 / 1024 / 1024, 1),
                    "percent": round(disk.percent, 1),
                },
                "network": {
                    "bytes_sent": net.bytes_sent,
                    "bytes_recv": net.bytes_recv,
                },
            }
        except Exception as e:
            return {"error": str(e)}
    
    def get_uptime(self) -> float:
        """Get server uptime in seconds."""
        return time.time() - self._start_time
    
    def get_endpoint_stats(self) -> dict:
        """Get per-endpoint statistics."""
        stats = {}
        for endpoint in self._requests:
            stats[endpoint] = {
                "requests_1min": sum(1 for ts, _ in self._requests[endpoint] if ts > time.time() - 60),
                "requests_5min": sum(1 for ts, _ in self._requests[endpoint] if ts > time.time() - 300),
                "errors_1min": sum(1 for ts, _ in self._errors[endpoint] if ts > time.time() - 60),
            }
        return stats
    
    def get_p56_purge_history(self) -> list:
        """Get P56 purge history with formatted timestamps."""
        history = []
        for ts, count, ip in self._p56_purges:
            history.append({
                "timestamp": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S"),
                "count": count,
                "ip": ip,
                "unix_ts": int(ts)
            })
        return list(reversed(history))  # Most recent first

    def get_delay_stats(self, window: int = 300, source: Optional[str] = None) -> dict:
        """Get delay statistics for the last window seconds.

        Args:
            window: Time window in seconds
            source: Optional filter by source (e.g., "vatsim")

        Returns:
            Dictionary with count, avg, min, max, p50, p95 statistics
        """
        cutoff = time.time() - window

        if source:
            recent = [delay for ts, delay, src in self._delays if ts > cutoff and src == source]
        else:
            recent = [delay for ts, delay, _ in self._delays if ts > cutoff]

        if not recent:
            return {"count": 0, "avg": 0, "min": 0, "max": 0, "p50": 0, "p95": 0, "current": 0}

        recent_sorted = sorted(recent)
        p50_idx = int(len(recent_sorted) * 0.50)
        p95_idx = int(len(recent_sorted) * 0.95)

        # Get current (most recent) delay
        current_delay = 0
        if self._delays:
            if source:
                for ts, delay, src in reversed(self._delays):
                    if src == source:
                        current_delay = delay
                        break
            else:
                _, current_delay, _ = self._delays[-1]

        return {
            "count": len(recent),
            "avg": round(sum(recent) / len(recent), 2),
            "min": round(min(recent), 2),
            "max": round(max(recent), 2),
            "p50": round(recent_sorted[p50_idx], 2) if recent_sorted else 0,
            "p95": round(recent_sorted[p95_idx], 2) if recent_sorted else 0,
            "current": round(current_delay, 2),
        }

    def get_delay_history(self, limit: int = 100, source: Optional[str] = None) -> list:
        """Get recent delay measurements for time-series graphing.

        Args:
            limit: Maximum number of data points to return
            source: Optional filter by source

        Returns:
            List of delay measurements with timestamps, suitable for line graphs
        """
        history = []
        delays_list = list(self._delays)

        if source:
            delays_list = [(ts, delay, src) for ts, delay, src in delays_list if src == source]

        for ts, delay, src in delays_list[-limit:]:
            history.append({
                "timestamp": datetime.fromtimestamp(ts).isoformat(),
                "delay_seconds": round(delay, 2),
                "source": src,
                "unix_ts": int(ts)
            })
        return history
    
    def get_summary(self) -> dict:
        """Get a comprehensive metrics summary."""
        return {
            "timestamp": datetime.now().isoformat(),
            "uptime_seconds": round(self.get_uptime(), 1),
            "active_users": self.get_active_users(),
            "request_rate": {
                "1min": round(self.get_request_rate(window=60), 2),
                "5min": round(self.get_request_rate(window=300), 2),
            },
            "error_rate": {
                "1min": round(self.get_error_rate(window=60), 2),
                "5min": round(self.get_error_rate(window=300), 2),
            },
            "delay": {
                "1min": self.get_delay_stats(window=60),
                "5min": self.get_delay_stats(window=300),
                "history": self.get_delay_history(limit=50),
            },
            "resources": self.get_resource_usage(),
            "endpoints": self.get_endpoint_stats(),
            "p56_purges": self.get_p56_purge_history(),
        }


# Global singleton
METRICS = MetricsTracker()
