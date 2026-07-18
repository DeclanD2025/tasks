from __future__ import annotations

import json

from app import services
from app.db.models import ActivityMetricDaily, HealthMetricDaily
from app.integrations.health_auto_export.parser import parse_payload
from app.integrations.health_auto_export.storage import upsert_metric_rows


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
                "name": "step_count", "units": "count",
                "data": [{"qty": 8200, "date": "2026-06-14 19:00:00 +0000"}],
            },
            {
                "name": "active_energy_burned", "units": "kcal",
                "data": [{"qty": 520, "date": "2026-06-14 19:00:00 +0000"}],
            },
            {
                "name": "apple_exercise_time", "units": "min",
                "data": [{"qty": 42, "date": "2026-06-14 19:00:00 +0000"}],
            },
            {
                "name": "respiratory_rate", "units": "count/min",
                "data": [{"qty": 15.4, "date": "2026-06-14 05:00:00 +0000"}],
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
    assert r["steps"] == 8200
    assert r["active_energy_kcal"] == 520
    assert r["exercise_minutes"] == 42
    assert r["respiratory_rate"] == 15.4
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


def test_resting_hr_falls_back_to_heart_rate_daily_min():
    """When there's no resting_heart_rate metric, the day's minimum heart rate
    (from the heart_rate stream's Min field) is used as a resting-HR proxy."""
    payload = {"data": {"metrics": [
        {"name": "heart_rate", "units": "count/min", "data": [
            {"Min": 59, "Max": 90, "Avg": 72, "date": "2026-06-14 09:00:00 +0000"},
            {"Min": 47, "Max": 60, "Avg": 53, "date": "2026-06-14 03:00:00 +0000"},
        ]},
    ]}}
    rows = parse_payload(payload)
    assert rows[0]["resting_hr"] == 47   # daily minimum across samples
    assert "heart_rate" not in rows[0]   # internal field is not emitted


def test_dedicated_resting_hr_wins_over_heart_rate_proxy():
    payload = {"data": {"metrics": [
        {"name": "heart_rate", "units": "count/min",
         "data": [{"Min": 40, "date": "2026-06-14 03:00:00 +0000"}]},
        {"name": "resting_heart_rate", "units": "bpm",
         "data": [{"qty": 55, "date": "2026-06-14 06:00:00 +0000"}]},
    ]}}
    rows = parse_payload(payload)
    assert rows[0]["resting_hr"] == 55   # real metric beats the HR-min proxy


def test_real_resting_hr_beats_proxy_across_merged_files(tmp_path):
    """The crux of the low-RHR bug: one file has only the heart_rate stream
    (yielding a low min proxy, e.g. 47) and another file for the SAME day has
    the real Resting Heart Rate metric (e.g. 58, which is HIGHER). The genuine
    value must win even though it's larger — the old min() merge kept the proxy.
    """
    from app.integrations.health_auto_export.parser import parse_folder

    proxy_file = {"data": {"metrics": [
        {"name": "heart_rate", "units": "count/min",
         "data": [{"Min": 47, "date": "2026-06-14 03:00:00 +0000"}]},
    ]}}
    real_file = {"data": {"metrics": [
        {"name": "resting_heart_rate", "units": "bpm",
         "data": [{"qty": 58, "date": "2026-06-14 06:00:00 +0000"}]},
    ]}}

    # Filenames are read in sorted order; check both orderings so the real
    # value wins whether it is read before or after the proxy.
    for label, proxy_name, real_name in (
        ("proxy_first", "a_proxy.json", "b_real.json"),
        ("real_first", "a_real.json", "b_proxy.json"),
    ):
        d = tmp_path / label
        d.mkdir()
        (d / proxy_name).write_text(json.dumps(proxy_file))
        (d / real_name).write_text(json.dumps(real_file))
        rows = parse_folder(d)
        assert rows[0]["resting_hr"] == 58, label


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


def test_stage_based_sleep_sums_real_stages_only():
    """HAE weekly exports stream sleep as stage segments (value=stage name,
    qty=hours). We sum Core/Deep/REM/Asleep and exclude Awake / In Bed."""
    payload = {"data": {"metrics": [
        {"name": "sleep_analysis", "units": "hr", "data": [
            {"value": "Awake", "qty": 0.5, "date": "2026-06-08 23:00:00 +0000"},
            {"value": "Core", "qty": 3.0, "date": "2026-06-08 23:30:00 +0000"},
            {"value": "Deep", "qty": 1.5, "date": "2026-06-09 02:00:00 +0000"},
            {"value": "REM", "qty": 2.0, "date": "2026-06-09 04:00:00 +0000"},
            {"value": "In Bed", "qty": 8.0, "date": "2026-06-08 22:30:00 +0000"},
        ]},
    ]}}
    rows = parse_payload(payload)
    # Core 3 + Deep 1.5 + REM 2 = 6.5h asleep; Awake & In Bed excluded.
    minutes = {r["day"]: r["sleep_minutes"] for r in rows}
    total = sum(v for v in minutes.values() if v)
    assert total == round(6.5 * 60)


def test_daily_summary_sleep_still_works():
    payload = {"data": {"metrics": [
        {"name": "sleep_analysis", "units": "hr",
         "data": [{"asleep": 7.5, "date": "2026-06-14 02:00:00 +0000"}]},
    ]}}
    rows = parse_payload(payload)
    assert rows[0]["sleep_minutes"] == 450


def test_overlapping_files_do_not_double_count(tmp_path):
    """The same day in two files (a daily AND a weekly export) must not sum its
    sleep / distance. The fuller value wins; it is never added together."""
    from app.integrations.health_auto_export.parser import parse_folder

    daily = {"data": {"metrics": [
        {"name": "sleep_analysis", "units": "hr",
         "data": [{"asleep": 5.0, "date": "2026-06-14 02:00:00 +0000"}]},
        {"name": "walking_running_distance", "units": "km",
         "data": [{"qty": 6.0, "date": "2026-06-14 18:00:00 +0000"}]},
    ]}}
    weekly = {"data": {"metrics": [
        {"name": "sleep_analysis", "units": "hr",
         "data": [{"asleep": 5.0, "date": "2026-06-14 02:00:00 +0000"}]},
        {"name": "walking_running_distance", "units": "km",
         "data": [{"qty": 6.3, "date": "2026-06-14 18:00:00 +0000"}]},
    ]}}
    (tmp_path / "DAILY-2026-06-14.json").write_text(json.dumps(daily))
    (tmp_path / "WEEKLY-2026-24.json").write_text(json.dumps(weekly))

    rows = {r["day"]: r for r in parse_folder(tmp_path)}
    r = rows["2026-06-14"]
    assert r["sleep_minutes"] == 300       # 5h, NOT 10h
    assert r["distance_km"] == 6.3         # the larger of 6.0 / 6.3, NOT 12.3


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


def test_workout_export_imports_completed_workout_with_route(tmp_path):
    from app.db.database import session_scope
    from app.db.models import Workout
    from app.integrations.health_auto_export.workouts import import_workouts_from_folder

    payload = {"data": {"workouts": [{
        "id": "W1",
        "name": "Outdoor Run",
        "start": "2026-06-24 18:26:45 +0100",
        "end": "2026-06-24 18:57:46 +0100",
        "duration": 1860.68,
        "distance": {"qty": 4.003, "units": "km"},
        "avgHeartRate": {"qty": 160.3, "units": "count/min"},
        "maxHeartRate": {"qty": 175, "units": "count/min"},
        "elevationUp": {"qty": 58.98, "units": "m"},
        "isIndoor": False,
        "location": "Outdoor",
        "route": [
            {"latitude": 55.8, "longitude": -4.02, "timestamp": "2026-06-24 18:26:45 +0100"},
            {"latitude": 55.801, "longitude": -4.021, "timestamp": "2026-06-24 18:26:46 +0100"},
        ],
    }]}}
    export_dir = tmp_path / "ORION"
    export_dir.mkdir()
    (export_dir / "ORION WORKOUT DATA-2026.json").write_text(json.dumps(payload))

    with session_scope() as session:
        assert import_workouts_from_folder(tmp_path, session, 1) == 1
        row = session.query(Workout).filter_by(source="health_auto_export", source_id="W1").one()
        assert row.sport_type == "run"
        assert row.duration_seconds == 1861
        assert row.distance_meters == 4003
        assert round(row.average_heart_rate, 1) == 160.3
        assert len(row.route_geometry) == 2


# Storage tests use 2025 dates to avoid the seeded mock data, which covers
# the last 30 days from "today".


def test_upsert_metric_rows_creates_health_metric_daily():
    from app.db.database import session_scope

    uid = services.get_default_user_id()
    records = [
        {
            "day": "2025-01-10",
            "sleep_minutes": 450,
            "hrv_ms": 55.0,
            "resting_hr": 52,
            "weight_kg": 78.5,
        }
    ]
    with session_scope() as session:
        count = upsert_metric_rows(session, uid, records)
        assert count == 1
        row = (
            session.query(HealthMetricDaily)
            .filter_by(user_id=uid, day="2025-01-10")
            .one()
        )
        assert row.sleep_minutes == 450
        assert row.hrv_ms == 55.0
        assert row.resting_hr == 52
        assert row.weight_kg == 78.5


def test_upsert_metric_rows_creates_activity_metric_daily():
    from app.db.database import session_scope

    uid = services.get_default_user_id()
    records = [
        {
            "day": "2025-01-11",
            "steps": 8200,
            "exercise_minutes": 42,
            "active_energy_kcal": 520,
        }
    ]
    with session_scope() as session:
        count = upsert_metric_rows(session, uid, records)
        assert count == 1
        row = (
            session.query(ActivityMetricDaily)
            .filter_by(user_id=uid, day="2025-01-11")
            .one()
        )
        assert row.steps == 8200
        assert row.active_minutes == 42
        assert row.extra["active_energy_kcal"] == 520


def test_upsert_metric_rows_stores_extra_keys():
    from app.db.database import session_scope

    uid = services.get_default_user_id()
    records = [
        {
            "day": "2025-01-12",
            "mood": 0.5,
            "mindful_minutes": 10,
            "distance_km": 4.2,
            "vo2max": 51.4,
            "respiratory_rate": 15.4,
        }
    ]
    with session_scope() as session:
        upsert_metric_rows(session, uid, records)
        row = (
            session.query(HealthMetricDaily)
            .filter_by(user_id=uid, day="2025-01-12")
            .one()
        )
        assert row.extra["mood"] == 0.5
        assert row.extra["mindful_minutes"] == 10
        assert row.extra["distance_km"] == 4.2
        assert row.extra["vo2max"] == 51.4
        assert row.extra["respiratory_rate"] == 15.4


def test_upsert_metric_rows_updates_existing_row():
    from app.db.database import session_scope

    uid = services.get_default_user_id()
    with session_scope() as session:
        upsert_metric_rows(
            session,
            uid,
            [{"day": "2025-01-13", "sleep_minutes": 400, "steps": 5000}],
        )
    with session_scope() as session:
        upsert_metric_rows(
            session,
            uid,
            [{"day": "2025-01-13", "sleep_minutes": 450, "hrv_ms": 60.0}],
        )
        row = (
            session.query(HealthMetricDaily)
            .filter_by(user_id=uid, day="2025-01-13")
            .one()
        )
        assert row.sleep_minutes == 450
        assert row.hrv_ms == 60.0
        activity = (
            session.query(ActivityMetricDaily)
            .filter_by(user_id=uid, day="2025-01-13")
            .one()
        )
        assert activity.steps == 5000


def test_upsert_metric_rows_empty_records():
    from app.db.database import session_scope

    uid = services.get_default_user_id()
    with session_scope() as session:
        assert upsert_metric_rows(session, uid, []) == 0


def test_upsert_metric_rows_no_activity_data_does_not_create_activity_row():
    from app.db.database import session_scope

    uid = services.get_default_user_id()
    records = [{"day": "2025-01-14", "sleep_minutes": 450}]
    with session_scope() as session:
        upsert_metric_rows(session, uid, records)
        health = (
            session.query(HealthMetricDaily)
            .filter_by(user_id=uid, day="2025-01-14")
            .one()
        )
        assert health.sleep_minutes == 450
        activity = (
            session.query(ActivityMetricDaily)
            .filter_by(user_id=uid, day="2025-01-14")
            .first()
        )
        assert activity is None


def test_upsert_metric_rows_idempotent():
    from app.db.database import session_scope

    uid = services.get_default_user_id()
    records = [{"day": "2025-01-15", "sleep_minutes": 480, "steps": 10000}]
    with session_scope() as session:
        upsert_metric_rows(session, uid, records)
    with session_scope() as session:
        upsert_metric_rows(session, uid, records)
        health_count = (
            session.query(HealthMetricDaily)
            .filter_by(user_id=uid, day="2025-01-15")
            .count()
        )
        activity_count = (
            session.query(ActivityMetricDaily)
            .filter_by(user_id=uid, day="2025-01-15")
            .count()
        )
        assert health_count == 1
        assert activity_count == 1


def test_upsert_metric_rows_backfills_activity_to_existing_health_day():
    from app.db.database import session_scope

    uid = services.get_default_user_id()
    with session_scope() as session:
        upsert_metric_rows(
            session, uid, [{"day": "2025-01-16", "sleep_minutes": 420}]
        )
    with session_scope() as session:
        upsert_metric_rows(
            session, uid, [{"day": "2025-01-16", "steps": 7000}]
        )
        health = (
            session.query(HealthMetricDaily)
            .filter_by(user_id=uid, day="2025-01-16")
            .one()
        )
        assert health.sleep_minutes == 420
        activity = (
            session.query(ActivityMetricDaily)
            .filter_by(user_id=uid, day="2025-01-16")
            .one()
        )
        assert activity.steps == 7000


def test_upsert_metric_rows_updates_extra_keys():
    from app.db.database import session_scope

    uid = services.get_default_user_id()
    with session_scope() as session:
        upsert_metric_rows(
            session, uid, [{"day": "2025-01-17", "mood": 0.5}]
        )
    with session_scope() as session:
        upsert_metric_rows(
            session, uid, [{"day": "2025-01-17", "mood": 0.8}]
        )
        row = (
            session.query(HealthMetricDaily)
            .filter_by(user_id=uid, day="2025-01-17")
            .one()
        )
        assert row.extra["mood"] == 0.8


def test_parse_payload_extracts_blood_pressure():
    payload = {"data": {"metrics": [
        {"name": "blood_pressure_systolic", "units": "mmHg",
         "data": [{"qty": 120, "date": "2026-06-14 08:00:00 +0000"}]},
        {"name": "blood_pressure_diastolic", "units": "mmHg",
         "data": [{"qty": 80, "date": "2026-06-14 08:00:00 +0000"}]},
    ]}}
    rows = parse_payload(payload)
    assert len(rows) == 1
    assert rows[0]["bp_systolic"] == 120
    assert rows[0]["bp_diastolic"] == 80


def test_upsert_metric_rows_stores_blood_pressure():
    from app.db.database import session_scope

    uid = services.get_default_user_id()
    records = [
        {
            "day": "2025-01-19",
            "bp_systolic": 118,
            "bp_diastolic": 76,
        }
    ]
    with session_scope() as session:
        upsert_metric_rows(session, uid, records)
        row = (
            session.query(HealthMetricDaily)
            .filter_by(user_id=uid, day="2025-01-19")
            .one()
        )
        assert row.extra["bp_systolic"] == 118
        assert row.extra["bp_diastolic"] == 76


def test_upsert_metric_rows_backfills_health_to_existing_activity_day():
    from app.db.database import session_scope

    uid = services.get_default_user_id()
    with session_scope() as session:
        upsert_metric_rows(
            session, uid, [{"day": "2025-01-18", "steps": 5000}]
        )
    with session_scope() as session:
        upsert_metric_rows(
            session, uid, [{"day": "2025-01-18", "sleep_minutes": 400}]
        )
        activity = (
            session.query(ActivityMetricDaily)
            .filter_by(user_id=uid, day="2025-01-18")
            .one()
        )
        assert activity.steps == 5000
        health = (
            session.query(HealthMetricDaily)
            .filter_by(user_id=uid, day="2025-01-18")
            .one()
        )
        assert health.sleep_minutes == 400
