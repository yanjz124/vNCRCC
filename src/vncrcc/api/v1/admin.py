"""Admin authentication helpers.

The admin password comes from the VNCRCC_ADMIN_PASSWORD environment variable
(loaded from .env by api/v1/p56.py at import time). Protected endpoints take
it in the ``X-Admin-Password`` header; ``POST /api/v1/admin/verify`` lets the
metrics page check a password without side effects (it used to probe
``/p56/purge``, which logged a fake purge and used up the purge rate limit).
"""
import hmac
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Request

from ...rate_limit import maybe_limit

ADMIN_HEADER = "X-Admin-Password"

router = APIRouter(prefix="/admin")


def password_ok(provided: Any) -> bool:
    """Constant-time comparison against the configured admin password."""
    expected = os.getenv("VNCRCC_ADMIN_PASSWORD")
    if not expected or not isinstance(provided, str) or not provided:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


async def require_admin(x_admin_password: Optional[str] = Header(default=None, alias=ADMIN_HEADER)) -> None:
    """FastAPI dependency: 403 unless the admin password header is correct."""
    if not os.getenv("VNCRCC_ADMIN_PASSWORD"):
        raise HTTPException(status_code=403, detail="Server admin password not configured")
    if not password_ok(x_admin_password):
        raise HTTPException(status_code=403, detail="Invalid or missing admin password")


@router.post("/verify")
@maybe_limit("6/minute")
async def verify(request: Request, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """Return 200 if the supplied password is correct, 403 otherwise."""
    if not os.getenv("VNCRCC_ADMIN_PASSWORD"):
        raise HTTPException(status_code=403, detail="Server admin password not configured")
    if not password_ok((payload or {}).get("password")):
        raise HTTPException(status_code=403, detail="Invalid password")
    return {"status": "ok"}
