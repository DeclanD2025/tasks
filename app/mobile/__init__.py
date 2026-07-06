"""Mobile companion read models for ORION.

The JSON snapshot remains the fallback/bootstrap path while CloudKit sync is
rolled out. Live sync metadata lives under ``app.sync``.
"""

from app.mobile.snapshot import build_mobile_snapshot, write_mobile_snapshot

__all__ = ["build_mobile_snapshot", "write_mobile_snapshot"]
