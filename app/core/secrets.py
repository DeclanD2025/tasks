"""Small OS secret-store wrapper.

Secrets must not live in SQLite, logs, git, or chat transcripts. ORION stores
credential material in the user's OS keychain and keeps only opaque references
inside the database.
"""

from __future__ import annotations

import platform
import subprocess


SERVICE_NAME = "ORION"


class SecretStoreError(RuntimeError):
    """Raised when the platform cannot store a requested secret securely."""


def store_secret(name: str, secret: str) -> str:
    """Store a secret and return an opaque local reference."""

    account = _account_name(name)
    value = secret.strip()
    if not value:
        raise SecretStoreError("Empty secrets are not stored.")
    if platform.system() != "Darwin":
        raise SecretStoreError("OS keychain storage is currently implemented for macOS only.")
    result = subprocess.run(
        [
            "security",
            "add-generic-password",
            "-s",
            SERVICE_NAME,
            "-a",
            account,
            "-w",
            value,
            "-U",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SecretStoreError("macOS Keychain rejected the secret.")
    return f"macos-keychain:{account}"


def read_secret(name: str) -> str | None:
    """Read a stored secret. Use sparingly and never log the return value."""

    account = _account_name(name)
    if platform.system() != "Darwin":
        return None
    result = subprocess.run(
        ["security", "find-generic-password", "-s", SERVICE_NAME, "-a", account, "-w"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def delete_secret(name: str) -> None:
    account = _account_name(name)
    if platform.system() != "Darwin":
        return
    subprocess.run(
        ["security", "delete-generic-password", "-s", SERVICE_NAME, "-a", account],
        check=False,
        capture_output=True,
        text=True,
    )


def _account_name(name: str) -> str:
    clean = "".join(ch for ch in name.strip().lower() if ch.isalnum() or ch in "._-")
    if not clean:
        raise SecretStoreError("Secret name is empty.")
    return f"orion.{clean}"
