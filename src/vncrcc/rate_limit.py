"""Rate limiting utilities for API endpoints."""
import os
import sys
from functools import wraps
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def get_rate_limit_key(request: Request) -> str:
    """Return empty string for localhost to exempt it from rate limiting, otherwise use IP."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else "unknown"
    
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
