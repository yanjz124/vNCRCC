"""Rate limiting utilities for API endpoints."""
import os
import sys
from functools import wraps
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


_LOOPBACK = ("127.0.0.1", "::1", "localhost")


def get_client_ip(request: Request) -> str:
    """Best-effort real client IP that cannot be spoofed via headers.

    Proxy headers are only trusted when the TCP peer is the local reverse
    proxy (nginx on loopback). nginx sets X-Real-IP to $remote_addr and
    *appends* $remote_addr to X-Forwarded-For, so the first XFF entry is
    whatever the client sent -- trusting it let anyone bypass rate limits
    (rotate fake IPs) or claim to be 127.0.0.1. Use X-Real-IP, else the last
    XFF hop (the one our proxy added).
    """
    peer = request.client.host if getattr(request, "client", None) else ""
    if peer in _LOOPBACK:
        real_ip = (request.headers.get("X-Real-IP") or "").strip()
        if real_ip:
            return real_ip
        forwarded = request.headers.get("X-Forwarded-For") or ""
        hops = [h.strip() for h in forwarded.split(",") if h.strip()]
        if hops:
            return hops[-1]
    return peer or "unknown"


def get_rate_limit_key(request: Request) -> str:
    """Return empty string for localhost to exempt it from rate limiting, otherwise use IP."""
    client_ip = get_client_ip(request)

    # Exempt localhost/internal calls
    if client_ip in ("127.0.0.1", "::1", "localhost"):
        return ""
    return client_ip


# Shared limiter instance - 20 requests per minute (1 per 3 seconds)
limiter = Limiter(key_func=get_rate_limit_key, default_limits=["20/minute"])

# Disable limiter during tests to allow calling route handlers without a Request object
if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("VNCRCC_TESTING") == "1" or "pytest" in sys.modules:
    limiter.enabled = False


def maybe_limit(limit: str):
    """Decorator factory that becomes a no-op during tests.

    During pytest runs or when VNCRCC_TESTING=1, return an identity decorator
    so route handlers can be invoked directly in unit tests without a Request.
    Otherwise, apply the slowapi limiter with the given limit.
    """
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("VNCRCC_TESTING") == "1" or "pytest" in sys.modules:
        def identity(f):
            return f
        return identity
    return limiter.limit(limit)


def apply_rate_limit(limit: str = "20/minute"):
    """Decorator to apply rate limiting to route handlers."""
    def decorator(func):
        return limiter.limit(limit)(func)
    return decorator
