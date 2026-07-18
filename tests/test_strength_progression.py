"""The progression rules engine (app/domains/strength/progression.py).

Pure-function tests against literal sets. Logic that will quietly shape years
of training has to be checkable by reading it, and every case here is one a
lifter actually hits.
"""

from __future__ import annotations

import pytest

from app.domains.strength.progression import (
    PerformedSet,
    amrap_triggered,
    deload,
    double_progression,
    fixed_load,
    percentage_based,
    propose,
    rir_based,
    rpe_based,
    top_set_backoff,
)


def _sets(*specs, set_type="working") -> list[PerformedSet]:
    return [
        PerformedSet(weight_kg=w, reps=r, rpe=rpe, set_type=set_type)
        for w, r, rpe in specs
    ]


# --------------------------------------------------------------------------- #
# Double progression — the brief's worked example
# --------------------------------------------------------------------------- #
def test_hitting_the_top_of_the_range_on_every_set_earns_the_load():
    """3×6–8: all three sets at 8 reps, at or under RPE 8 → add weight."""
    result = double_progression(
        _sets((60, 8, 7.5), (60, 8, 8.0), (60, 8, 8.0)),
        rep_min=6, rep_max=8, increment_kg=2.5, target_rpe=8.0,
    )
    assert result.action == "increase"
    assert result.next_weight_kg == 62.5
    assert result.next_reps == 6  # back to the bottom of the range
    assert result.delta_kg == 2.5
    assert "hit 8 reps" in result.reason


def test_one_good_set_does_not_earn_the_load():
    """Otherwise the first set drives an increase the later sets cannot support."""
    result = double_progression(
        _sets((60, 8, 7.0), (60, 7, 8.0), (60, 6, 9.0)),
        rep_min=6, rep_max=8, increment_kg=2.5,
    )
    assert result.action == "hold"
    assert result.next_weight_kg == 60


def test_reps_met_but_rpe_blown_does_not_earn_the_load():
    """8 reps at RPE 10 is not the same event as 8 at RPE 8. Treating them
    alike is how a lifter ends up grinding."""
    result = double_progression(
        _sets((60, 8, 10.0), (60, 8, 10.0), (60, 8, 10.0)),
        rep_min=6, rep_max=8, target_rpe=8.0,
    )
    assert result.action == "hold"


def test_an_rpe_capped_rule_will_not_increase_on_unrated_sets():
    """The cap cannot be checked, so the increase is not justified — and the
    proposal says exactly that rather than quietly ignoring the cap."""
    result = double_progression(
        _sets((60, 8, None), (60, 8, None), (60, 8, None)),
        rep_min=6, rep_max=8, target_rpe=8.0,
    )
    assert result.action == "hold"
    assert "no RPE was recorded" in result.reason


def test_repeatedly_missing_the_minimum_reduces_the_load():
    result = double_progression(
        _sets((60, 5, 9.5), (60, 4, 10.0), (60, 4, 10.0)),
        rep_min=6, rep_max=8, increment_kg=2.5, consecutive_misses=1, miss_limit=2,
    )
    assert result.action == "reduce"
    assert result.next_weight_kg == 55.0  # 90%, snapped to the increment
    assert "consecutive" in result.reason


def test_a_single_miss_holds_rather_than_reducing():
    """One bad session is a bad session, not a trend."""
    result = double_progression(
        _sets((60, 5, 9.5), (60, 5, 10.0)),
        rep_min=6, rep_max=8, consecutive_misses=0, miss_limit=2,
    )
    assert result.action == "hold"


def test_no_history_is_inconclusive_not_a_hold():
    """"Hold" is a decision. "I have nothing to go on" is not, and the UI needs
    to be able to tell them apart."""
    result = double_progression([], rep_min=6, rep_max=8)
    assert result.action == "none"
    assert result.conclusive is False


def test_warmups_are_ignored_by_the_rule():
    warmup = PerformedSet(weight_kg=100, reps=8, rpe=5, set_type="warmup")
    working = _sets((60, 8, 8.0), (60, 8, 8.0))
    result = double_progression([warmup, *working], rep_min=6, rep_max=8, increment_kg=2.5)
    assert result.action == "increase"
    assert result.next_weight_kg == 62.5  # from 60, not from the 100 kg warm-up


# --------------------------------------------------------------------------- #
# Other rules
# --------------------------------------------------------------------------- #
def test_fixed_load_adds_weight_when_the_target_is_met():
    result = fixed_load(_sets((100, 5, None), (100, 5, None)), target_reps=5, increment_kg=2.5)
    assert result.action == "increase"
    assert result.next_weight_kg == 102.5


def test_fixed_load_repeats_when_the_target_is_missed():
    result = fixed_load(_sets((100, 5, None), (100, 4, None)), target_reps=5)
    assert result.action == "hold"


def test_rpe_steering_raises_the_load_when_it_was_too_easy():
    result = rpe_based(_sets((100, 5, 6.0), (100, 5, 6.5)), target_rpe=8.0, increment_kg=2.5)
    assert result.action == "increase"
    assert result.next_weight_kg == 102.5


def test_rpe_steering_lowers_the_load_when_it_was_too_hard():
    result = rpe_based(_sets((100, 5, 9.5), (100, 5, 10.0)), target_rpe=8.0, increment_kg=2.5)
    assert result.action == "reduce"
    assert result.next_weight_kg == 97.5


def test_rpe_steering_uses_the_mean_not_the_last_set():
    """Fatigue means the final set almost always rates highest. Steering on it
    alone would ratchet the load down over time."""
    result = rpe_based(_sets((100, 5, 7.0), (100, 5, 7.0), (100, 5, 9.0)),
                       target_rpe=8.0, increment_kg=2.5)
    assert result.action == "hold"  # mean is 7.67, inside tolerance


def test_rpe_steering_needs_ratings():
    result = rpe_based(_sets((100, 5, None)), target_rpe=8.0)
    assert result.conclusive is False


def test_rir_steering_mirrors_rpe_on_the_inverted_scale():
    sets = [PerformedSet(weight_kg=100, reps=5, rir=4), PerformedSet(weight_kg=100, reps=5, rir=4)]
    result = rir_based(sets, target_rir=2.0, increment_kg=2.5)
    assert result.rule == "rir_target"
    assert result.action == "increase"  # 4 RIR = RPE 6, easier than the RPE 8 target


def test_percentage_rounds_to_a_loadable_weight():
    result = percentage_based(one_rm_kg=140, percent=0.75, reps=5, increment_kg=2.5)
    assert result.next_weight_kg == 105.0  # 105.0 exactly
    assert "75%" in result.reason


def test_amrap_well_past_target_earns_a_double_jump():
    """The load was clearly too light; a single step wastes another session
    finding that out."""
    sets = [PerformedSet(weight_kg=100, reps=11, set_type="amrap")]
    result = amrap_triggered(sets, amrap_target=5, increment_kg=2.5)
    assert result.action == "increase"
    assert result.next_weight_kg == 105.0
    assert "6 over" in result.reason


def test_amrap_just_meeting_target_earns_a_single_step():
    sets = [PerformedSet(weight_kg=100, reps=5, set_type="amrap")]
    result = amrap_triggered(sets, amrap_target=5, increment_kg=2.5)
    assert result.next_weight_kg == 102.5


def test_amrap_below_target_holds():
    sets = [PerformedSet(weight_kg=100, reps=3, set_type="amrap")]
    assert amrap_triggered(sets, amrap_target=5).action == "hold"


def test_a_session_with_no_amrap_set_is_inconclusive():
    assert amrap_triggered(_sets((100, 5, 8.0)), amrap_target=5).conclusive is False


def test_top_set_backoff_derives_the_backoff_from_the_new_top():
    result = top_set_backoff(
        _sets((120, 3, 8.0), (100, 6, 7.0)), backoff_percent=0.85,
        increment_kg=2.5, target_reps=3,
    )
    assert result.action == "increase"
    assert result.next_weight_kg == 122.5
    assert result.inputs["backoffKg"] == 105.0


def test_deload_drops_to_the_configured_fraction():
    result = deload(current_weight_kg=100, factor=0.9, increment_kg=2.5)
    assert result.action == "deload"
    assert result.next_weight_kg == 90.0


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #
def test_manual_progression_proposes_nothing_and_says_so():
    result = propose("manual", _sets((100, 5, 8.0)))
    assert result.action == "none"
    assert result.conclusive is True


def test_an_unknown_rule_is_inconclusive_rather_than_an_exception():
    """A typo in a programme should not stop a session from being logged."""
    result = propose("bench_vibes", _sets((100, 5, 8.0)))
    assert result.conclusive is False
    assert "implemented" in result.reason


def test_percentage_without_a_max_on_file_says_so():
    result = propose("percentage", [], config={"percent": 0.8})
    assert result.conclusive is False
    assert "1RM" in result.reason


def test_every_proposal_carries_its_rule_reason_and_inputs():
    """Nothing is applied automatically, so the operator has to be able to
    judge the proposal — which means seeing what it looked at."""
    result = propose(
        "double_progression",
        _sets((60, 8, 7.5), (60, 8, 8.0)),
        config={"repMin": 6, "repMax": 8, "incrementKg": 2.5},
    )
    payload = result.as_dict()
    assert payload["rule"] == "double_progression"
    assert payload["reason"]
    assert payload["inputs"]["repRange"] == [6, 8]
    assert payload["inputs"]["sets"]
