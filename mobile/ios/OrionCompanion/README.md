# ORION Companion iOS

Native SwiftUI companion for the desktop ORION app.

## What is implemented

- Five-tab companion shell: Today, Tasks, Capture, Insights, Settings.
- Face ID/device-auth app lock.
- SwiftData local cache for sync records and queued captures.
- Explicit CloudKit client path through `OrionSyncKit`.
- Snapshot JSON import fallback for offline/manual testing.
- iCloud/CloudKit entitlements template for `iCloud.com.declandundas.orion`.

## Build requirements

This target requires a full Xcode install with the iPhone Simulator SDK. The
current Command Line Tools-only setup cannot run `xcodebuild` or `simctl`.

Open:

```bash
open mobile/ios/OrionCompanion/OrionCompanion.xcodeproj
```

Then set your Apple Developer team on the `OrionCompanion` target. The bundle ID
is `com.declandundas.orion.ios`.

## Desktop sync bridge

Prepare the desktop SQLite sync metadata and validate the helper JSON bridge:

```bash
uv run pytest tests/test_sync_foundation.py tests/test_sync_helper.py
swift build --package-path mobile/OrionSyncKit
uv run python scripts/sync_cloudkit_outbox.py
```

Apply pulled helper records or fixture envelopes into the desktop database:

```bash
uv run python scripts/apply_cloudkit_records.py pulled-records.json
```

Real CloudKit writes require a signed helper/bundle with the iCloud container
enabled:

```bash
uv run python scripts/sync_cloudkit_outbox.py --push --helper /path/to/orion-sync-helper
```

## Snapshot fallback

The old import path remains useful while signing is being configured:

```bash
uv run python scripts/export_mobile_snapshot.py
```

Import the generated JSON from the iOS app’s Settings tab.
