#!/usr/bin/env python3
"""Export ORION's read-only mobile snapshot JSON."""

from __future__ import annotations

import argparse

from app.core.logging import configure_logging
from app.db.database import init_db
from app.db.seed import seed
from app.mobile import write_mobile_snapshot
from app.services import get_default_user_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        "-o",
        default="dist/mobile/orion-mobile-snapshot.json",
        help="Where to write the JSON snapshot.",
    )
    parser.add_argument("--days", type=int, default=30, help="History window for charts.")
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Write compact JSON instead of pretty-printed JSON.",
    )
    parser.add_argument(
        "--no-seed",
        action="store_true",
        help="Fail instead of creating demo data when the database has no user.",
    )
    args = parser.parse_args()

    configure_logging()
    init_db()
    if get_default_user_id() is None:
        if args.no_seed:
            raise SystemExit("No ORION user exists. Run the app or seed the database first.")
        seed()

    output = write_mobile_snapshot(args.output, days=args.days, pretty=not args.compact)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
