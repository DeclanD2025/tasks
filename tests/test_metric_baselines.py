"""Baselines exclude days the device was not actually worn.

Health Auto Export writes a row whether or not the watch was on, so the series
carries real days and fragments. Averaging them together halved the sleep
baseline every delta on Today was drawn against — a 27-minute "night" counted
as much as an eight-hour one.
"""

from __future__ import annotations

from app.domains.health import derived, metric_details as md


# Declan's real production sleep week (hours), 2026-07-12..18. Four of these
# seven "nights" are fragments; the naive mean is 3.9h, which is what the app
# was showing as a baseline against an 8h 12m night.
REAL_SLEEP_WEEK = [1.28, 1.38, 1.20, 0.45, 6.32, 8.20, 8.20]


def test_the_bug_this_fixes():
    """The naive mean is the number that was on screen; the gated one is not."""
    naive = sum(REAL_SLEEP_WEEK) / len(REAL_SLEEP_WEEK)
    assert round(naive, 1) == 3.9  # what Today showed

    baseline, coverage = md._baseline(REAL_SLEEP_WEEK, "sleep", 7, minimum=3)
    assert baseline == 7.57  # mean of the three real nights
    assert coverage == {"used": 3, "of": 7}


def test_sleep_bounds_come_from_the_derived_layer():
    """One definition of a plausible night, not two that can drift."""
    low, high = md._PLAUSIBLE_RANGE["sleep"]
    assert low == derived.MIN_PLAUSIBLE_SLEEP_MIN / 60.0
    assert high == derived.MAX_PLAUSIBLE_SLEEP_MIN / 60.0


def test_fragment_days_are_excluded():
    assert md._plausible([0.5, 1.0, 7.0, 8.0], "sleep") == [7.0, 8.0]
    assert md._plausible([16, 42, 4045, 10327], "steps") == [4045, 10327]


def test_implausibly_high_values_are_excluded_too():
    """A 20-hour "night" is a tracker glitch, not a lie-in."""
    assert md._plausible([7.5, 20.0], "sleep") == [7.5]


def test_ungated_metrics_keep_every_reading():
    """HRV only exists when the watch measured it — there is no fragment case."""
    values = [40.0, 98.3, 36.5, 111.5]
    assert md._plausible(values, "hrv") == values
    assert md._plausible(values, "resting_hr") == values


def test_none_values_are_dropped_whatever_the_metric():
    assert md._plausible([None, 7.0, None], "sleep") == [7.0]
    assert md._plausible([None, 55.0], "hrv") == [55.0]


def test_too_few_plausible_days_yields_no_baseline():
    """Better to say "baseline building" than to average two days confidently."""
    baseline, coverage = md._baseline([0.4, 0.5, 0.6, 8.0, 7.5], "sleep", 7, minimum=3)
    assert baseline is None
    assert coverage == {"used": 2, "of": 5}


def test_a_fully_captured_week_reports_full_coverage():
    week = [7.0, 7.5, 8.0, 6.5, 7.2, 7.8, 8.1]
    baseline, coverage = md._baseline(week, "sleep", 7, minimum=3)
    assert coverage == {"used": 7, "of": 7}
    assert baseline == round(sum(week) / 7, 2)


def test_baseline_only_looks_at_its_own_window():
    """A 30-day history must not leak into the 7-day baseline."""
    values = [0.0] * 23 + [7.0] * 7
    baseline, coverage = md._baseline(values, "sleep", 7, minimum=3)
    assert baseline == 7.0
    assert coverage == {"used": 7, "of": 7}


def test_typical_band_ignores_fragments():
    """A band drawn through unworn days makes real low days look normal."""
    values = [0.3, 0.4, 0.5, 0.6] + [7.0, 7.2, 7.4, 7.6, 7.8, 8.0, 8.2, 8.4]
    gated = md._typical_band(values, "sleep")
    ungated = md._typical_band(values)
    assert gated is not None and ungated is not None
    assert gated[0] > ungated[0]  # the gated floor sits up in real-sleep territory
    assert gated[0] >= 7.0


def test_empty_history_is_handled():
    baseline, coverage = md._baseline([], "sleep", 7, minimum=3)
    assert baseline is None
    assert coverage == {"used": 0, "of": 0}
