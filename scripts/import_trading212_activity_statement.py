from __future__ import annotations

import argparse
from pathlib import Path

from app.integrations.trading212.activity_statement import import_activity_statement


DEFAULT_PATH = Path("~/Downloads/Activity-Statement-2025-12-01-2026-06-24.pdf").expanduser()


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Trading 212 Activity Statement holdings into ORION.")
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--account-value", type=float, default=266.24)
    parser.add_argument("--cash-value", type=float, default=0.0)
    args = parser.parse_args()

    result = import_activity_statement(
        args.path,
        account_value=args.account_value,
        cash_value=args.cash_value,
    )
    print(
        "Imported Trading 212 Activity Statement: "
        f"{result['positions']} open positions, "
        f"generated {result['generated_on']}, "
        f"account value £{args.account_value:,.2f}, "
        f"cash £{args.cash_value:,.2f}"
    )


if __name__ == "__main__":
    main()
