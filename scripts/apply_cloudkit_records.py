#!/usr/bin/env python3
"""Apply pulled ORION CloudKit record envelopes to the desktop database."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.core.logging import configure_logging
from app.db.database import init_db
from app.sync import apply_incoming_records, ensure_sync_foundation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input",
        nargs="?",
        default="-",
        help="JSON file containing a list of envelopes/helper records, or '-' for stdin.",
    )
    parser.add_argument("--user-id", type=int, help="Target ORION user ID. Defaults to first user.")
    args = parser.parse_args()

    configure_logging()
    init_db()
    ensure_sync_foundation()

    payload = _read_json(args.input)
    records = payload.get("records", payload) if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise SystemExit("Input must be a JSON list, or an object with a 'records' list.")

    result = apply_incoming_records(records, user_id=args.user_id)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _read_json(path: str):
    if path == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
