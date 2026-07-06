"""Import the local Trading 212 holdings screenshot snapshot into ORION."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.integrations.trading212.holdings_snapshot import import_holdings_snapshot


DEFAULT_PATH = Path("data/trading212_holdings_snapshot_2026-06-25.json")


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Trading 212 holdings snapshot.")
    parser.add_argument("path", nargs="?", default=str(DEFAULT_PATH), help="holdings JSON path")
    args = parser.parse_args()

    path = Path(args.path).expanduser()
    if not path.exists():
        print(f"Snapshot not found: {path}")
        return 1
    result = import_holdings_snapshot(path)
    print(
        "Imported Trading 212 holdings snapshot: "
        f"{result['holdings']} holding(s), "
        f"£{result['investments_value']:,.2f} invested."
    )
    print(f"Captured on: {result['captured_on']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
