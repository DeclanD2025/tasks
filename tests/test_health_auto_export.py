from __future__ import annotations

import json

from app.integrations.health_auto_export.parser import parse_payload


# A realistic Health Auto Export payload (trimmed). Covers the metrics ORION
# consumes, with the documented {qty, date} point shape and "yyyy-MM-dd HH:mm:ss Z".
_PAYLOAD = {
    "data": {
        "metrics": [
            {
                "name": "heart_rate_variability", "units": "ms",
                "data": [
                    {"qty": 50.0, "date": "2026-06-14 07:00:00 +0000"},
                    {"qty": 60.0, "date": "2026-06-14 22:00:00 +0000"},
                ],
            },
            {
                "name": "resting_heart_rate", "units": "bpm",
                "data": [{"qty": 52, "date": "2026-06-14 06:00:00 +0000"}],
            },
            {
                "name": "vo2_max", "units": "mL/min·kg",
                "data": [{"qty": 51.4, "date": "2026-06-14 18:00:00 +0000"}],
            },
            {
                "name": "walking_running_distance", "units": "km",
                "data": [
                    {"qty": 4.0, "date": "2026-06-14 18:00:00 +0000"},
                    {"qty": 6.0, "date": "2026-06-14 19:00:00 +0000"},
                ],
            },
            {
                "name": "sleep_analysis", "units": "hr",
                "data": [{"asleep": 7.5, "date": "2026-06-14 02:00:00 +0000"}],
            },
            {
                "name": "mindful_minutes", "units": "min",
                "data": [{"qty": 10, "date": "2026-06-14 07:00:00 +0000"}],
            },
            {
                "name": "state_of_mind", "units": "",
                "data": [
                    {"valence": 0.4, "date": "2026-06-14 20:00:00 +0000"},
                    {"valence": 0.6, "date": "2026-06-14 21:00:00 +0000"},
                ],
            },
            {
                "name": "some_unmapped_metric", "units": "x",
                "data": [{"qty": 1, "date": "2026-06-14 09:00:00 +0000"}],
            },
        ]
    }
}


def test_parse_payload_maps_all_orion_fields():
    rows = parse_payload(_PAYLOAD)
    assert len(rows) == 1
    r = rows[0]
    assert r["day"] == "2026-06-14"
    assert r["hrv_ms"] == 55.0          # mean(50, 60)
    assert r["resting_hr"] == 52
    assert r["vo2max"] == 51.4
    assert r["distance_km"] == 10.0     # 4 + 6 summed
    assert r["sleep_minutes"] == 450    # 7.5h asleep
    assert r["mindful_minutes"] == 10
    assert r["mood"] == 0.5             # mean(0.4, 0.6)
    assert r["source"] == "health_auto_export"


def test_unmapped_metrics_ignored_and_missing_is_none():
    payload = {"data": {"metrics": [
        {"name": "blood_glucose", "units": "mg/dL",
         "data": [{"qty": 95, "date": "2026-06-14 08:00:00 +0000"}]},
    ]}}
    rows = parse_payload(payload)
    # the day exists only if at least one mapped metric matched -> none here
    assert rows == []


def test_alias_matching_is_tolerant_of_spacing_case():
    payload = {"data": {"metrics": [
        {"name": "Heart Rate Variability", "units": "ms",
         "data": [{"qty": 48, "date": "2026-06-14 07:00:00 +0000"}]},
    ]}}
    rows = parse_payload(payload)
    assert rows[0]["hrv_ms"] == 48.0


def test_parse_file_roundtrip(tmp_path):
    from app.integrations.health_auto_export.parser import parse_file

    p = tmp_path / "HealthAutoExport-2026-06-14.json"
    p.write_text(json.dumps(_PAYLOAD))
    rows = parse_file(p)
    assert rows[0]["hrv_ms"] == 55.0


def test_parse_folder_merges_category_files(tmp_path):
    """HAE splits exports by category; a folder may hold Health Metrics AND a
    separate State of Mind file. They must merge on the same day."""
    from app.integrations.health_auto_export.parser import parse_folder

    metrics_file = {"data": {"metrics": [
        {"name": "heart_rate_variability", "units": "ms",
         "data": [{"qty": 60, "date": "2026-06-14 07:00:00 +0000"}]},
    ]}}
    mood_file = {"data": {"metrics": [
        {"name": "state_of_mind", "units": "",
         "data": [{"valence": 0.5, "date": "2026-06-14 20:00:00 +0000"}]},
    ]}}
    (tmp_path / "HealthMetrics.json").write_text(json.dumps(metrics_file))
    (tmp_path / "StateOfMind.json").write_text(json.dumps(mood_file))

    rows = parse_folder(tmp_path)
    assert len(rows) == 1
    r = rows[0]
    assert r["hrv_ms"] == 60.0   # from HealthMetrics.json
    assert r["mood"] == 0.5      # from StateOfMind.json — merged same day


def test_parse_folder_handles_state_of_mind_array(tmp_path):
    # Some HAE categories emit a dedicated array rather than a named metric.
    from app.integrations.health_auto_export.parser import parse_folder

    payload = {"data": {"stateOfMind": [
        {"valence": 0.2, "date": "2026-06-14 09:00:00 +0000"},
        {"valence": 0.8, "date": "2026-06-14 21:00:00 +0000"},
    ]}}
    (tmp_path / "StateOfMind.json").write_text(json.dumps(payload))
    rows = parse_folder(tmp_path)
    assert rows[0]["mood"] == 0.5  # mean(0.2, 0.8)
