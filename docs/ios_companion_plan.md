# ORION iOS Companion Plan

This plan gets ORION onto an iPhone without changing the current desktop app
architecture. The desktop app remains Python, PySide6, and local-first SQLite.
The phone app starts as a read-only companion that imports a compact snapshot,
then graduates to live sync only where the data source already supports it.

## Current Constraints

- ORION is a native desktop app built with Python and PySide6/Qt.
- The existing UI is a desktop command centre with a 1040 px minimum window.
- PySide6 does not provide a simple supported path for packaging the current Qt
  Widgets desktop app as an iOS app.
- The local SQLite database can sync between Macs through iCloud Drive, but an
  iPhone app should not directly open that SQLite file.
- Several data paths are already phone-friendly: iCloud Calendar, Health Auto
  Export, and Supabase tasks.

## Target Shape

1. Keep the desktop app unchanged as the canonical ORION workbench.
2. Add a read-only mobile JSON contract.
3. Build a SwiftUI iOS companion that can import that JSON from Files/iCloud.
4. Add live native integrations one by one:
   - Tasks: Supabase REST.
   - Calendar: EventKit on iOS.
   - Health/Fitness: HealthKit or Health Auto Export.
5. Decide later whether to add a small private API, CloudKit, or Supabase tables
   for derived ORION metrics.

## Phase 0 - Added Now

- `app/mobile/snapshot.py` builds a stable JSON payload for iOS.
- `scripts/export_mobile_snapshot.py` writes that payload locally.
- `mobile/ios/OrionCompanion` contains a minimal SwiftUI companion scaffold.

Export a snapshot:

```bash
uv run python scripts/export_mobile_snapshot.py
```

The default output is:

```text
dist/mobile/orion-mobile-snapshot.json
```

Move that file into iCloud Drive, open the iOS app, and import it from Files.

## Phase 1 - Real Device Prototype

1. Open `mobile/ios/OrionCompanion/OrionCompanion.xcodeproj` in Xcode.
2. Set the signing team to your Apple ID.
3. Connect your iPhone and choose it as the run destination.
4. Build and run.
5. Import `orion-mobile-snapshot.json` from iCloud Drive.

This proves the device workflow, the SwiftUI shell, and the mobile data contract
before changing ORION's core architecture.

## Phase 2 - First Live Sync

Start with tasks because ORION already has a Supabase connector and task rows
are low-risk compared with finance or health.

- Add a Swift `TasksClient`.
- Read open tasks from the existing Supabase table.
- Keep writes off by default until row-level security and auth boundaries are
  reviewed.
- Once safe, enable completion toggles and new task creation.

## Phase 3 - Native Apple Data

- Calendar: use EventKit directly on iPhone for upcoming events.
- Health/Fitness: use HealthKit where possible, keeping Health Auto Export as a
  fallback for metrics that are easier to export than query.

## Phase 4 - Derived ORION Metrics

Choose one:

- Private local network endpoint from the Mac app.
- CloudKit container for derived read models.
- Supabase/Postgres tables for selected mobile read models.

The mobile JSON contract should remain the compatibility layer even after live
sync exists.

## Guardrails

- Do not port the PySide desktop UI to iOS.
- Do not put banking or health secrets in the iOS scaffold.
- Do not make the iPhone open the Mac SQLite database directly.
- Keep the first phone app read-only until signing, import, and schema stability
  are proven.
