from __future__ import annotations

import textwrap

from app.integrations.apple_health.parser import parse_export


_SAMPLE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <HealthData locale="en_GB">
      <Record type="HKQuantityTypeIdentifierHeartRateVariabilitySDNN" unit="ms"
              startDate="2026-06-14 07:00:00 +0000" endDate="2026-06-14 07:00:00 +0000" value="55"/>
      <Record type="HKQuantityTypeIdentifierHeartRateVariabilitySDNN" unit="ms"
              startDate="2026-06-14 22:00:00 +0000" endDate="2026-06-14 22:00:00 +0000" value="65"/>
      <Record type="HKQuantityTypeIdentifierRestingHeartRate" unit="count/min"
              startDate="2026-06-14 06:00:00 +0000" endDate="2026-06-14 06:00:00 +0000" value="52"/>
      <Record type="HKQuantityTypeIdentifierBodyMass" unit="kg"
              startDate="2026-06-14 06:30:00 +0000" endDate="2026-06-14 06:30:00 +0000" value="79.2"/>
      <Record type="HKCategoryTypeIdentifierSleepAnalysis"
              value="HKCategoryValueSleepAnalysisAsleepCore"
              startDate="2026-06-14 00:00:00 +0000" endDate="2026-06-14 04:00:00 +0000"/>
      <Record type="HKCategoryTypeIdentifierSleepAnalysis"
              value="HKCategoryValueSleepAnalysisAsleepREM"
              startDate="2026-06-14 04:00:00 +0000" endDate="2026-06-14 06:00:00 +0000"/>
      <StateOfMind startDate="2026-06-14 20:00:00 +0000" valence="0.4"/>
      <StateOfMind startDate="2026-06-14 21:00:00 +0000" valence="0.6"/>
    </HealthData>
""")


def test_parse_export_extracts_per_day_metrics(tmp_path):
    xml = tmp_path / "export.xml"
    xml.write_text(_SAMPLE)
    rows = parse_export(xml)
    assert len(rows) == 1
    r = rows[0]
    assert r["day"] == "2026-06-14"
    assert r["hrv_ms"] == 60.0           # mean(55, 65)
    assert r["resting_hr"] == 52
    assert r["weight_kg"] == 79.2
    assert r["sleep_minutes"] == 360     # 6 hours asleep (core + REM)
    assert r["mood"] == 0.5              # mean(0.4, 0.6)
    assert r["source"] == "apple_health_export"


def test_parse_export_missing_file_raises(tmp_path):
    import pytest

    with pytest.raises(FileNotFoundError):
        parse_export(tmp_path / "nope.xml")
