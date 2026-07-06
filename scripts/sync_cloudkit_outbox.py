#!/usr/bin/env python3
"""Push ORION's pending CloudKit outbox through the Swift helper."""

from __future__ import annotations

import argparse
import json

from app.core.logging import configure_logging
from app.db.database import init_db
from app.sync import ensure_sync_foundation, sync_pending_outbox


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--push",
        action="store_true",
        help="Perform real CloudKit writes. Defaults to validation-only dry run.",
    )
    parser.add_argument("--limit", type=int, default=200, help="Maximum outbox rows to send.")
    parser.add_argument(
        "--helper",
        help="Path to a signed orion-sync-helper binary. Defaults to ORION_SYNC_HELPER or SwiftPM.",
    )
    args = parser.parse_args()

    configure_logging()
    init_db()
    ensure_sync_foundation()
    helper_command = [args.helper] if args.helper else None
    response = sync_pending_outbox(
        dry_run=not args.push,
        limit=args.limit,
        helper_command=helper_command,
    )
    print(json.dumps(response, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
