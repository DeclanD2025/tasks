"""Store a Starling Personal Access Token in macOS Keychain for ORION.

Run from the project root:

    uv run python scripts/store_finance_access_token.py

Paste the Starling token at the hidden prompt. The token is not echoed, logged,
written to git, or stored in SQLite. ORION stores the secret in macOS Keychain
under service "ORION" and records only a non-secret local reference in the
database.
"""

from __future__ import annotations

import os
import subprocess
from getpass import getpass

from sqlalchemy import select

from app.core.secrets import read_secret, store_secret
from app.db.database import init_db, session_scope
from app.db.models import DataSource, Domain, SourceStatus, utcnow
from app.services import get_default_user_id


PROVIDER_KEY = "open_banking"
SECRET_FIELD = "access_token"
SECRET_NAME = f"finance.{PROVIDER_KEY}.{SECRET_FIELD}"


def main() -> int:
    print("ORION Starling token importer")
    token = os.environ.get("ORION_FINANCE_ACCESS_TOKEN", "").strip()
    source = "environment"
    if os.environ.get("ORION_FINANCE_TOKEN_FROM_CLIPBOARD") == "1":
        token = _clipboard_text().strip()
        source = "clipboard"
    if not token:
        print("Paste the Starling Personal Access Token below. Input is hidden.")
        token = getpass("Token: ").strip()
        source = "hidden prompt"
    if not token:
        print("No token entered; nothing stored.")
        return 1

    init_db()
    user_id = get_default_user_id()
    if user_id is None:
        print("No ORION user exists yet. Launch ORION once, then rerun this script.")
        return 1

    ref = store_secret(SECRET_NAME, token)
    if not read_secret(SECRET_NAME):
        print("Keychain write did not verify. Nothing was written to SQLite.")
        return 1
    if source == "clipboard":
        _clear_clipboard()

    with session_scope() as session:
        source = session.scalars(
            select(DataSource).where(
                DataSource.user_id == user_id,
                DataSource.key == PROVIDER_KEY,
            )
        ).first()
        if source is None:
            source = DataSource(
                user_id=user_id,
                key=PROVIDER_KEY,
                name="Bank Accounts",
                domain=Domain.finance,
                status=SourceStatus.disconnected,
            )
            session.add(source)
            session.flush()

        extra = dict(source.extra or {})
        refs = dict(extra.get("credential_refs") or {})
        refs[SECRET_FIELD] = ref
        extra["credential_refs"] = refs
        extra["credential_state"] = "token_stored"
        extra["credential_stored_at"] = utcnow().isoformat()
        source.extra = extra

    print("Stored in macOS Keychain.")
    print(f"Reference saved for ORION: {ref}")
    if source == "clipboard":
        print("Clipboard cleared.")
    print("Next: run ORION sync to import Starling accounts, balances and feed items.")
    return 0


def _clipboard_text() -> str:
    result = subprocess.run(
        ["pbpaste"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    return result.stdout


def _clear_clipboard() -> None:
    subprocess.run(
        ["pbcopy"],
        input="",
        check=False,
        text=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
