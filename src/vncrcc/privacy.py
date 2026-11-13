"""Strip pilot/controller identity from everything the API sends out.

Internally the service still keys aircraft, tracks and P-56 entries by VATSIM
CID (that is how the feed identifies a connection). Before any JSON leaves the
server it goes through :func:`redact`, which

* drops ``name`` / ``realName`` from any object that describes a person
  (an object carrying ``cid`` or ``callsign``), and
* replaces every CID with an opaque, stable token (an HMAC of the CID under a
  server-side secret), both as a value and where CIDs are used as map keys.

The token is stable for the life of the secret, so the web UI can keep using
it to match aircraft, flight paths and logged entries, but it cannot be turned
back into a CID without the secret. Endpoints that take an identifier from a
client (``/p56/track``, ``/p56/purge``) map the token back with
:func:`resolve`.

The secret comes from ``VNCRCC_PSEUDONYM_SECRET`` or, if unset, from a random
key generated once and kept in ``data/.pseudonym_key``.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
from pathlib import Path
from typing import Any, Dict, Optional

TOKEN_PREFIX = "id-"

# Objects with one of these keys describe a pilot or controller.
_PERSON_MARKERS = ("cid", "callsign")
# Personal fields removed from such objects.
_PERSON_FIELDS = ("name", "realName", "real_name")
# Values under these keys are CIDs.
_CID_VALUE_KEYS = ("cid", "identifier")
# Dicts under these keys are maps of {cid: ...}.
_CID_MAP_PARENTS = ("history", "data", "current_inside", "tracks")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_KEY_PATH = Path(os.environ.get("VNCRCC_PSEUDONYM_KEY_PATH") or (_REPO_ROOT / "data" / ".pseudonym_key"))

_lock = threading.Lock()
_secret: Optional[bytes] = None
_forward: Dict[str, str] = {}
_reverse: Dict[str, str] = {}


def _load_secret() -> bytes:
    global _secret
    if _secret is not None:
        return _secret
    with _lock:
        if _secret is not None:
            return _secret
        env = os.environ.get("VNCRCC_PSEUDONYM_SECRET")
        if env:
            _secret = env.encode("utf-8")
            return _secret
        try:
            if _KEY_PATH.exists():
                raw = _KEY_PATH.read_text().strip()
                if raw:
                    _secret = raw.encode("utf-8")
                    return _secret
            _KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
            raw = secrets.token_hex(32)
            _KEY_PATH.write_text(raw)
            try:
                os.chmod(_KEY_PATH, 0o600)
            except OSError:
                pass
            _secret = raw.encode("utf-8")
        except OSError:
            # Read-only disk: fall back to a per-process key (tokens change
            # on restart, which only resets the UI's remembered selections).
            _secret = secrets.token_hex(32).encode("utf-8")
        return _secret


def _is_cid(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value > 0
    return isinstance(value, str) and value.isdigit()


def pseudonymize(cid: Any) -> Any:
    """Opaque token for a CID; non-CID values are returned unchanged."""
    if not _is_cid(cid):
        return cid
    key = str(int(cid))
    tok = _forward.get(key)
    if tok is None:
        digest = hmac.new(_load_secret(), key.encode("utf-8"), hashlib.sha256).hexdigest()
        tok = TOKEN_PREFIX + digest[:12]
        with _lock:
            _forward[key] = tok
            _reverse[tok] = key
    return tok


def resolve(token: Any) -> Optional[str]:
    """CID for a token handed out earlier, or None if unknown."""
    if not isinstance(token, str):
        return None
    return _reverse.get(token)


def _redact_event_key(value: str) -> str:
    """'<cid>:<recorded_at>' -> '<token>:<recorded_at>'."""
    head, sep, tail = value.partition(":")
    if sep and _is_cid(head):
        return f"{pseudonymize(head)}:{tail}"
    return value


def redact(obj: Any, parent: Optional[str] = None) -> Any:
    """Return a redacted copy of a JSON-like structure (input is not mutated)."""
    if isinstance(obj, dict):
        is_person = any(k in obj for k in _PERSON_MARKERS)
        cid_map = parent in _CID_MAP_PARENTS
        out: Dict[Any, Any] = {}
        for k, v in obj.items():
            if is_person and k in _PERSON_FIELDS:
                continue
            if k in _CID_VALUE_KEYS:
                out[k] = pseudonymize(v)
                continue
            nk = pseudonymize(k) if (cid_map and isinstance(k, str) and k.isdigit()) else k
            out[nk] = redact(v, k if isinstance(k, str) else None)
        return out
    if isinstance(obj, list):
        if parent == "keys":
            return [_redact_event_key(x) if isinstance(x, str) else redact(x) for x in obj]
        return [redact(x, parent) for x in obj]
    return obj


def _reset_for_tests(secret: Optional[str] = None) -> None:
    global _secret
    with _lock:
        _secret = secret.encode("utf-8") if secret else None
        _forward.clear()
        _reverse.clear()
