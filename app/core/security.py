"""Security helpers for ORION (local-first MVP).

Scope for this phase:
  * a passphrase-based unlock gate for the login screen
  * redaction helpers so sensitive payloads never hit the logs

This is intentionally minimal. The TODOs below mark where production-grade
secret management and at-rest encryption must be added before ORION stores
real financial or health data.
"""

from __future__ import annotations

import hashlib
import hmac
import re

from app.core.config import get_settings

# Demo passphrase used only in development when ORION_UNLOCK_PASSPHRASE is unset.
# This unlocks the bundled mock dataset; it never protects real data.
DEMO_PASSPHRASE = "orion"


def verify_unlock(passphrase: str) -> bool:
    """Verify the unlock passphrase for the login/unlock screen.

    TODO(security): replace this with a real KDF (argon2id / scrypt) and use the
    derived key to encrypt the SQLite database at rest (e.g. SQLCipher). Today
    this only gates UI access to local mock data; it is NOT a data-protection
    boundary.
    """
    settings = get_settings()
    expected = settings.unlock_passphrase
    if not expected:
        # No passphrase configured: allow the demo passphrase in development,
        # and require an explicit one in production.
        if settings.is_production:
            return False
        expected = DEMO_PASSPHRASE
    # Constant-time compare to avoid timing leaks.
    return hmac.compare_digest(_hash(passphrase), _hash(expected))


def _hash(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


_TOKEN_RE = re.compile(r"(token|secret|password|api[_-]?key)", re.IGNORECASE)


def redact(mapping: dict) -> dict:
    """Return a shallow copy of ``mapping`` with secret-looking values masked.

    Use before logging any config or payload dict.
    """
    out = {}
    for key, value in mapping.items():
        if _TOKEN_RE.search(str(key)) and value:
            out[key] = "***redacted***"
        else:
            out[key] = value
    return out
