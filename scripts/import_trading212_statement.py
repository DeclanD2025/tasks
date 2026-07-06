"""Import a Trading 212 transactions statement into ORION finance.

Default input:
    ~/Downloads/Transactions-Statement-2025-12-01-2026-06-24.pdf
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app.integrations.trading212.statement import import_statement


DEFAULT_PATH = Path.home() / "Downloads" / "Transactions-Statement-2025-12-01-2026-06-24.pdf"


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Trading 212 statement data.")
    parser.add_argument("path", nargs="?", default=str(DEFAULT_PATH), help="statement PDF path")
    args = parser.parse_args()

    path = Path(args.path).expanduser()
    if not path.exists():
        print(f"Statement not found: {path}")
        return 1
    result = import_statement(path)
    print(
        "Imported Trading 212 statement: "
        f"{result['accounts']} new account(s), "
        f"{result['balances']} balance update(s), "
        f"{result['transactions']} transaction(s)."
    )
    print(f"Statement date: {result['generated_on']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
