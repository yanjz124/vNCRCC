"""Rate limiting utilities for API endpoints."""
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


# Shared limiter instance - 6 requests per minute (1 per 10 seconds)
limiter = Limiter(key_func=get_rate_limit_key, default_limits=["6/minute"])


def apply_rate_limit(limit: str = "6/minute"):
    """Decorator to apply rate limiting to route handlers."""
    def decorator(func):
        return limiter.limit(limit)(func)
    return decorator
