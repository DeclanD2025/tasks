from __future__ import annotations

import json

from app.mobile import build_mobile_snapshot, write_mobile_snapshot


def test_mobile_snapshot_contract_shape():
    payload = build_mobile_snapshot()

    assert payload["schema_version"] == 1
    assert payload["user"]["id"]
    assert payload["overview"]["metrics"]
    assert "tasks" in payload and "counts" in payload["tasks"]
    assert "calendar" in payload and "upcoming" in payload["calendar"]

    # Guard the Swift companion's easiest path: the payload is plain JSON.
    encoded = json.dumps(payload)
    assert "generated_at" in encoded


def test_write_mobile_snapshot(tmp_path):
    output = write_mobile_snapshot(tmp_path / "orion-mobile-snapshot.json")

    assert output.exists()
    decoded = json.loads(output.read_text(encoding="utf-8"))
    assert decoded["schema_version"] == 1
