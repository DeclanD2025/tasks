"""Strength calculations (app/domains/strength/calc.py).

These are the numbers every chart, record and progression decision is built
from, so the tests are deliberately concrete: real loads, real rep counts, and
the awkward cases — assisted reps, unilateral sets, unrated effort, absurd rep
counts — that quietly corrupt a training log when handled loosely.
"""

from __future__ import annotations

import pytest

from app.domains.strength import calc


# --------------------------------------------------------------------------- #
# Units
# --------------------------------------------------------------------------- #
def test_pounds_convert_to_kilograms_and_back():
    assert calc.lb_to_kg(225) == pytest.approx(102.058, abs=1e-3)
    assert calc.kg_to_lb(calc.lb_to_kg(225)) == pytest.approx(225.0)


def test_to_kg_passes_through_kilograms_untouched():
    """A kg value must not be silently scaled — that would corrupt on re-save."""
    assert calc.to_kg(100.0, "kg") == 100.0
    assert calc.to_kg(100.0, "") == 100.0
    assert calc.to_kg(100.0, "lb") == pytest.approx(45.359, abs=1e-3)


def test_changing_display_units_does_not_change_stored_work():
    """The unit preference is a display concern. 100 kg is 100 kg whether the
    operator reads it as kg or lb, and volume must not move when they switch."""
    a = calc.SetInput(weight_kg=100.0, reps=5)
    assert calc.set_volume_kg(a) == 500.0
    # Same lift entered in pounds, normalised on the way in.
    b = calc.SetInput(weight_kg=calc.to_kg(220.462, "lb"), reps=5)
    assert calc.set_volume_kg(b) == pytest.approx(500.0, abs=0.01)


def test_loads_round_to_what_the_gym_can_actually_make():
    assert calc.round_to_increment(62.3, 2.5) == 62.5
    assert calc.round_to_increment(61.0, 5.0) == 60.0
    # A zero or negative increment must not divide by zero.
    assert calc.round_to_increment(62.3, 0) == 62.3


# --------------------------------------------------------------------------- #
# Set classification
# --------------------------------------------------------------------------- #
def test_legacy_and_foreign_set_type_spellings_normalise():
    """The old tracker wrote "warm-up"; other apps write "dropset". Normalising
    on read avoids a migration and keeps future imports from splitting stats."""
    assert calc.normalise_set_type("warm-up") == "warmup"
    assert calc.normalise_set_type("Warm Up") == "warmup"
    assert calc.normalise_set_type("dropset") == "drop"
    assert calc.normalise_set_type("rest-pause") == "rest_pause"
    assert calc.normalise_set_type(None) == "working"
    assert calc.normalise_set_type("") == "working"


def test_warmups_are_not_working_sets():
    assert calc.is_working_set("working") is True
    assert calc.is_working_set("top_set") is True
    assert calc.is_working_set("warm-up") is False
    assert calc.is_working_set("technique") is False


def test_an_unrated_working_set_is_not_assumed_hard():
    """Otherwise the hard-set count tracks rating diligence, not training — and
    would jump the moment the operator stopped entering RPE."""
    assert calc.is_hard_set("working", rpe=None, rir=None) is False
    assert calc.is_hard_set("working", rpe=8.0) is True
    assert calc.is_hard_set("working", rpe=6.0) is False
    assert calc.is_hard_set("working", rir=1.0) is True
    assert calc.is_hard_set("working", rir=4.0) is False


def test_a_set_to_failure_is_hard_without_a_rating():
    assert calc.is_hard_set("working", to_failure=True) is True
    assert calc.is_hard_set("failure") is True


def test_a_hard_warmup_is_still_not_a_hard_set():
    """Ramping to a heavy single in warm-up is real effort, but counting it
    would let a warm-up ramp inflate weekly hard-set volume."""
    assert calc.is_hard_set("warmup", rpe=9.0) is False


# --------------------------------------------------------------------------- #
# Effective load
# --------------------------------------------------------------------------- #
def test_external_load_is_just_the_weight():
    s = calc.SetInput(weight_kg=100.0, reps=5, load_type="external")
    assert calc.effective_load_kg(s) == 100.0


def test_a_bodyweight_set_is_not_zero_load():
    """Recording a push-up as 0 kg would erase it from every volume total."""
    s = calc.SetInput(reps=20, load_type="bodyweight", bodyweight_kg=95.0)
    assert calc.effective_load_kg(s) == pytest.approx(95.0 * 0.65)
    assert calc.set_volume_kg(s) > 0


def test_bodyweight_factor_overrides_the_default():
    s = calc.SetInput(reps=10, load_type="bodyweight", bodyweight_kg=95.0, bodyweight_factor=1.0)
    assert calc.effective_load_kg(s) == 95.0


def test_weighted_bodyweight_adds_to_full_bodyweight():
    """A +20 kg weighted pull-up moves bodyweight plus the belt, not 20 kg."""
    s = calc.SetInput(weight_kg=20.0, reps=5, load_type="weighted_bodyweight", bodyweight_kg=95.0)
    assert calc.effective_load_kg(s) == 115.0


def test_assistance_reduces_load_so_needing_less_help_reads_as_progress():
    heavy_help = calc.SetInput(reps=8, load_type="assisted", bodyweight_kg=95.0, assistance_kg=40.0)
    light_help = calc.SetInput(reps=8, load_type="assisted", bodyweight_kg=95.0, assistance_kg=20.0)
    assert calc.effective_load_kg(heavy_help) == 55.0
    assert calc.effective_load_kg(light_help) == 75.0
    assert calc.set_volume_kg(light_help) > calc.set_volume_kg(heavy_help)


def test_assistance_exceeding_bodyweight_floors_at_zero_not_negative():
    s = calc.SetInput(reps=5, load_type="assisted", bodyweight_kg=95.0, assistance_kg=200.0)
    assert calc.effective_load_kg(s) == 0.0


def test_missing_bodyweight_falls_back_rather_than_inventing_a_body_mass():
    """A made-up 80 kg would be wrong *and* look authoritative."""
    s = calc.SetInput(reps=10, load_type="bodyweight", bodyweight_kg=None)
    assert calc.effective_load_kg(s) == 0.0


# --------------------------------------------------------------------------- #
# Volume
# --------------------------------------------------------------------------- #
def test_set_volume_is_load_times_reps():
    assert calc.set_volume_kg(calc.SetInput(weight_kg=100.0, reps=5)) == 500.0


def test_a_zero_weight_set_still_counts_its_reps_but_no_tonnage():
    """Bodyweight squats logged as external 0 kg: honest zero, not a crash."""
    s = calc.SetInput(weight_kg=0.0, reps=20, load_type="external")
    assert calc.set_volume_kg(s) == 0.0
    assert calc.total_reps(s) == 20


def test_unilateral_sets_logged_per_side_count_both_limbs():
    """8 reps per arm at 20 kg is 320 kg of work — the limb did it twice."""
    s = calc.SetInput(weight_kg=20.0, left_reps=8, right_reps=8)
    assert calc.total_reps(s) == 16
    assert calc.set_volume_kg(s) == 320.0


def test_unilateral_sides_may_carry_different_loads():
    s = calc.SetInput(left_reps=8, right_reps=6, left_weight_kg=20.0, right_weight_kg=22.5)
    assert calc.set_volume_kg(s) == pytest.approx(20.0 * 8 + 22.5 * 6)


def test_duration_sets_report_no_tonnage():
    """A 60-second plank has no meaningful volume; inventing one pollutes every
    total it lands in."""
    s = calc.SetInput(duration_seconds=60.0, reps=None, set_type="working")
    assert calc.set_volume_kg(s) == 0.0


# --------------------------------------------------------------------------- #
# Estimated 1RM
# --------------------------------------------------------------------------- #
def test_epley_brzycki_and_lombardi_produce_their_published_values():
    assert calc.estimate_1rm(100, 5, formula="epley").value == pytest.approx(116.67, abs=0.01)
    assert calc.estimate_1rm(100, 5, formula="brzycki").value == pytest.approx(112.5, abs=0.01)
    assert calc.estimate_1rm(100, 5, formula="lombardi").value == pytest.approx(117.46, abs=0.01)


def test_a_single_is_measured_not_estimated():
    """Every formula should collapse to the lifted weight at one rep. Epley
    does not (it returns 1.033x), and reporting a measured single as 3% heavier
    than it was is how a fake PR gets created."""
    result = calc.estimate_1rm(140, 1, formula="epley")
    assert result.value == 140.0
    assert result.measured is True
    assert result.valid is True


def test_high_rep_sets_are_refused_not_estimated():
    """A 25-rep set says a lot about endurance and almost nothing about a 1RM.
    The old tracker capped reps at 30 and estimated anyway."""
    result = calc.estimate_1rm(60, 25)
    assert result.value is None
    assert result.valid is False
    assert "beyond" in result.reason
    assert not result  # falsy, so callers cannot use it by accident


def test_the_rep_limit_is_configurable_for_deliberate_analysis():
    result = calc.estimate_1rm(60, 20, max_reps=30)
    assert result.valid is True
    assert result.value is not None


def test_missing_load_or_reps_yields_no_estimate():
    assert calc.estimate_1rm(None, 5).valid is False
    assert calc.estimate_1rm(100, None).valid is False
    assert calc.estimate_1rm(0, 5).valid is False


def test_an_unknown_formula_is_an_error_not_a_silent_default():
    with pytest.raises(ValueError):
        calc.estimate_1rm(100, 5, formula="mayhew")


def test_estimate_records_which_formula_produced_it():
    """Two estimates from different formulas are not comparable, so a stored
    record has to say which one it came from."""
    assert calc.estimate_1rm(100, 5, formula="brzycki").formula == "brzycki"


def test_weight_for_reps_inverts_the_estimate():
    e1rm = calc.estimate_1rm(100, 5, formula="epley").value
    assert calc.weight_for_reps(e1rm, 5, formula="epley") == pytest.approx(100.0, abs=0.01)
    e1rm_b = calc.estimate_1rm(100, 5, formula="brzycki").value
    assert calc.weight_for_reps(e1rm_b, 5, formula="brzycki") == pytest.approx(100.0, abs=0.01)


def test_best_e1rm_ignores_warmups():
    """A heavy warm-up single would otherwise outrank the working sets."""
    sets = [
        calc.SetInput(weight_kg=120.0, reps=1, set_type="warmup"),
        calc.SetInput(weight_kg=100.0, reps=5, set_type="working"),
    ]
    best = calc.best_e1rm(sets)
    assert best is not None
    assert best.value == pytest.approx(116.67, abs=0.01)


# --------------------------------------------------------------------------- #
# Effort scales
# --------------------------------------------------------------------------- #
def test_rpe_and_rir_are_inverse_on_the_standard_scale():
    assert calc.rir_to_rpe(2) == 8.0
    assert calc.rpe_to_rir(8) == 2.0
    assert calc.rir_to_rpe(None) is None
    assert calc.rpe_to_rir(None) is None


def test_effort_conversions_stay_inside_the_scale():
    assert calc.rir_to_rpe(15) == 1.0
    assert calc.rpe_to_rir(-5) == 10.0  # clamped, not negative RIR


def test_intensity_bands_report_unknown_rather_than_guessing():
    assert calc.intensity_band(None) == "unknown"
    assert calc.intensity_band(0.90) == "heavy"
    assert calc.intensity_band(0.75) == "moderate"
    assert calc.intensity_band(0.50) == "light"


# --------------------------------------------------------------------------- #
# Muscle attribution
# --------------------------------------------------------------------------- #
def test_a_set_splits_across_primary_and_secondary_muscles():
    out = calc.attribute_set_to_muscles("Chest", ["Triceps", "Shoulders"])
    assert out == {"Chest": 1.0, "Triceps": 0.5, "Shoulders": 0.5}


def test_a_muscle_listed_twice_is_counted_once():
    """A mis-tagged exercise would otherwise silently award 1.5 sets."""
    out = calc.attribute_set_to_muscles("Chest", ["Chest", "Triceps"])
    assert out == {"Chest": 1.0, "Triceps": 0.5}


def test_indirect_weighting_is_configurable():
    """The 0.5 is a convention for comparability, not a physiological constant,
    so it must be adjustable rather than baked in."""
    out = calc.attribute_set_to_muscles(
        "Back", ["Biceps"], weighting=calc.MuscleWeighting(primary=1.0, secondary=0.25)
    )
    assert out == {"Back": 1.0, "Biceps": 0.25}


# --------------------------------------------------------------------------- #
# Plate maths
# --------------------------------------------------------------------------- #
def test_plates_solve_a_standard_loading():
    """Asserting the achieved weight, not one specific decomposition: 25+15 and
    20+20 both load 100 kg in two plates, and either is a correct answer."""
    sol = calc.plates_for(100.0)
    assert sol.achieved_kg == 100.0
    assert sol.exact is True
    assert sum(sol.per_side) == 40.0  # (100 - 20 bar) / 2 per side


def test_plates_report_the_nearest_loadable_weight_rather_than_pretending():
    sol = calc.plates_for(101.0)
    assert sol.exact is False
    assert sol.achieved_kg == pytest.approx(100.0)
    assert "nearest" in sol.note


def test_an_empty_bar_needs_no_plates():
    sol = calc.plates_for(20.0)
    assert sol.per_side == []
    assert sol.exact is True


def test_a_target_below_the_bar_is_flagged_not_negative():
    sol = calc.plates_for(15.0)
    assert sol.per_side == []
    assert sol.exact is False
    assert "below the empty bar" in sol.note


# --------------------------------------------------------------------------- #
# Session aggregates
# --------------------------------------------------------------------------- #
def _session() -> list[calc.SetInput]:
    return [
        calc.SetInput(weight_kg=60.0, reps=8, set_type="warmup"),
        calc.SetInput(weight_kg=100.0, reps=5, set_type="working", rpe=8.0),
        calc.SetInput(weight_kg=100.0, reps=5, set_type="working", rpe=9.0),
        calc.SetInput(weight_kg=100.0, reps=4, set_type="working", rpe=6.0),
    ]


def test_session_volume_excludes_warmups_by_default():
    """Warm-up tonnage would make sessions incomparable session to session."""
    assert calc.session_volume_kg(_session()) == 1400.0
    assert calc.session_volume_kg(_session(), working_only=False) == 1880.0


def test_working_and_hard_set_counts_are_different_numbers():
    sets = _session()
    assert calc.count_working_sets(sets) == 3
    assert calc.count_hard_sets(sets) == 2  # the RPE 6 set is not hard


def test_session_rpe_load_is_none_when_unrated():
    """An unrated session must not read as a session with no load."""
    assert calc.session_rpe_load(None, 60) is None
    assert calc.session_rpe_load(8.0, None) is None
    assert calc.session_rpe_load(8.0, 60) == 480.0
