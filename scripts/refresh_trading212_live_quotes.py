from __future__ import annotations

from app.integrations.trading212.live_quotes import refresh_live_quotes


def main() -> None:
    result = refresh_live_quotes()
    print(
        "Refreshed Trading 212 live quotes: "
        f"{result.get('holdings', 0)} holdings, "
        f"£{float(result.get('investments_value') or 0.0):,.2f} invested, "
        f"£{float(result.get('account_value') or 0.0):,.2f} account value"
    )
    missing = result.get("missing") or []
    if missing:
        print("Missing quote symbols:", ", ".join(missing))


if __name__ == "__main__":
    main()
