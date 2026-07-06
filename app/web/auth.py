"""Session-cookie auth for the web layer.

The unlock passphrase (see ``core.security.verify_unlock``) gates access, the
same way the desktop login screen does. On success the browser gets a signed,
expiring token; the signing secret is generated once per install and stored in
the ORION app-data directory, so sessions survive server restarts but never
leave this machine.

This protects a LAN-served UI over local data — it is not a hardened internet
boundary. Do not port-forward this server to the public internet.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path

from app.core.config import get_settings

SESSION_COOKIE = "orion_session"
SESSION_TTL_SECONDS = 30 * 24 * 3600  # 30 days


def _secret_path() -> Path:
    return get_settings().data_dir / "web_session.secret"


def _secret() -> bytes:
    # Deployed containers have ephemeral filesystems; ORION_WEB_SECRET keeps
    # sessions valid across restarts there. Locally the file is simpler.
    env_secret = os.environ.get("ORION_WEB_SECRET", "")
    if env_secret:
        return hashlib.sha256(env_secret.encode("utf-8")).digest()
    path = _secret_path()
    if path.exists():
        return path.read_bytes()
    value = secrets.token_bytes(32)
    path.write_bytes(value)
    path.chmod(0o600)
    return value


def issue_token(now: float | None = None) -> str:
    expires = int((now or time.time()) + SESSION_TTL_SECONDS)
    payload = f"orion-web.v1.{expires}"
    signature = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{signature}"


def verify_token(token: str | None, now: float | None = None) -> bool:
    if not token or "." not in token:
        return False
    expires_raw, signature = token.split(".", 1)
    try:
        expires = int(expires_raw)
    except ValueError:
        return False
    if expires < (now or time.time()):
        return False
    payload = f"orion-web.v1.{expires}"
    expected = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)
