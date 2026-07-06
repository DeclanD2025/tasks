# OrionSyncKit

Shared Swift package for ORION CloudKit sync.

## Products

- `OrionSyncKit`: Codable sync envelope, CloudKit record mapping, and CloudKit client.
- `orion-sync-helper`: stdin/stdout helper executable for the Python desktop app.

## Local validation

```bash
swift build --package-path mobile/OrionSyncKit
printf '%s' '{"operation":"dryRun","records":[]}' \
  | swift run --package-path mobile/OrionSyncKit orion-sync-helper
```

`swift test` requires a full Xcode install that includes XCTest. The current
Command Line Tools-only environment can build the package but cannot run XCTest.

## Helper protocol

Input:

```json
{
  "operation": "dryRun",
  "records": []
}
```

Output:

```json
{
  "ok": true,
  "count": 0
}
```

Use `operation: "push"` only from a signed app/helper with access to
`iCloud.com.declandundas.orion`.

Pulled records should be emitted as either a JSON list of ORION envelopes or an
object with a `records` list. The desktop app applies them with:

```bash
uv run python scripts/apply_cloudkit_records.py pulled-records.json
```
