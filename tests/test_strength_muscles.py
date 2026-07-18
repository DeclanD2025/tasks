"""The detailed muscle model (app/domains/strength/muscles.py).

The point of the 27-muscle model is that "Shoulders" is not a muscle anyone
trains — front, side and rear delts respond to different movements, and a
programme can hammer one while never touching another. These tests pin the
distinctions that make that legible, and the honesty guards that stop
stabiliser work reading as training.
"""

from __future__ import annotations

import pytest

from app.domains.strength import calc, muscles


def _share(slugs: list[tuple[str, str]]) -> dict[str, float]:
    """Percentage share of weighted sets across a list of (slug, coarse)."""
    weighted: dict[str, float] = {}
    for slug, coarse in slugs:
        attribution = muscles.attribution_for(slug, coarse)
        for muscle, (value, _tier) in calc.attribute_set_detailed(attribution).items():
            weighted[muscle] = weighted.get(muscle, 0.0) + value
    total = sum(weighted.values()) or 1.0
    return {m: round(v / total * 100, 1) for m, v in weighted.items()}


# --------------------------------------------------------------------------- #
# Anatomy
# --------------------------------------------------------------------------- #
def test_every_muscle_belongs_to_a_region():
    """An unregioned muscle would vanish from the rollup without warning."""
    for muscle in muscles.ALL_MUSCLES:
        assert muscles.region_for(muscle) in muscles.REGION_ORDER


def test_the_shoulder_heads_are_separate_muscles():
    """The whole reason for the model: a programme can hammer front delts and
    never touch rear delts, and "Shoulders: 27%" hides that completely."""
    assert muscles.region_for("Front delt") == "Shoulders"
    assert muscles.region_for("Rear delt") == "Shoulders"
    assert muscles.region_for("Side delt") == "Shoulders"

    press = muscles.attribution_for("dumbbell-shoulder-press")
    fly = muscles.attribution_for("rear-delt-fly")
    assert "Front delt" in press["primary"]
    assert "Rear delt" not in press["primary"] + press["secondary"]
    assert "Rear delt" in fly["primary"]


def test_incline_and_flat_pressing_hit_different_chest_regions():
    flat = muscles.attribution_for("bench-press")
    incline = muscles.attribution_for("incline-bench-press")
    assert flat["primary"] == ["Mid chest"]
    assert incline["primary"] == ["Upper chest"]


def test_seated_and_standing_calf_work_target_different_muscles():
    """Knee-flexed biases soleus, knee-extended biases gastrocnemius. It is the
    only reason both exercises exist."""
    assert muscles.attribution_for("seated-calf-raise")["primary"] == ["Soleus"]
    assert muscles.attribution_for("standing-calf-raise")["primary"] == ["Gastrocnemius"]


def test_triceps_heads_are_split_by_movement():
    """Overhead work biases the long head; pushdowns the lateral. Lifters
    program around this."""
    overhead = muscles.attribution_for("overhead-tricep-extension")
    pushdown = muscles.attribution_for("tricep-pushdown")
    assert overhead["primary"] == ["Triceps (long head)"]
    assert pushdown["primary"] == ["Triceps (lateral)"]


def test_hammer_curls_are_brachialis_led():
    assert muscles.attribution_for("hammer-curl")["primary"][0] == "Brachialis"


# --------------------------------------------------------------------------- #
# Attribution
# --------------------------------------------------------------------------- #
def test_a_bench_press_includes_its_stabilisers():
    """Rotator cuff and upper traps do real work holding a press together.
    Attributing bench to chest and triceps alone pretends they did nothing."""
    attribution = muscles.attribution_for("bench-press")
    assert "Rotator cuff" in attribution["stabiliser"]
    assert "Upper traps" in attribution["stabiliser"]


def test_stabilisers_count_for_less_than_synergists():
    """Counting a stabiliser equal to a synergist would make benching look like
    trap training."""
    w = calc.MuscleWeighting()
    assert w.primary > w.secondary > w.stabiliser > 0


def test_a_muscle_in_two_tiers_is_counted_once_at_its_highest():
    attribution = {
        "primary": ["Mid chest"],
        "secondary": ["Mid chest", "Front delt"],
        "stabiliser": ["Mid chest"],
    }
    result = calc.attribute_set_detailed(attribution)
    assert result["Mid chest"] == (1.0, "primary")


def test_the_tier_travels_with_the_share():
    """So the UI can keep direct work visually distinct from stabiliser work —
    they are different claims and must not merge into one bar."""
    result = calc.attribute_set_detailed(muscles.attribution_for("bench-press"))
    assert result["Mid chest"][1] == "primary"
    assert result["Front delt"][1] == "secondary"
    assert result["Rotator cuff"][1] == "stabiliser"


def test_an_unmapped_exercise_degrades_to_its_coarse_group():
    """A custom exercise should still land somewhere real rather than being
    attributed to nothing and silently vanishing from the chart."""
    attribution = muscles.attribution_for("some-custom-machine", "Chest")
    assert attribution["primary"] == ["Mid chest"]
    assert attribution["inferred"] is True


def test_an_unmapped_exercise_with_no_coarse_group_claims_nothing():
    """Better a gap than an invented attribution."""
    attribution = muscles.attribution_for("mystery-lift", "")
    assert attribution["primary"] == []


def test_the_weighting_is_configurable():
    """These are conventions, not physiological constants."""
    w = calc.MuscleWeighting(primary=1.0, secondary=0.3, stabiliser=0.1)
    result = calc.attribute_set_detailed(muscles.attribution_for("bench-press"), weighting=w)
    assert result["Front delt"][0] == 0.3
    assert result["Rotator cuff"][0] == 0.1


# --------------------------------------------------------------------------- #
# A real session
# --------------------------------------------------------------------------- #
def test_the_upper_body_session_splits_sensibly():
    """Declan's 18 July session: 3 bench, 3 dumbbell shoulder press, 3 pushdown.

    Pinned because it is the case that proves the model produces something a
    person would recognise rather than anatomically-plausible noise.
    """
    share = _share(
        [("bench-press", "Chest")] * 3
        + [("dumbbell-shoulder-press", "Shoulders")] * 3
        + [("tricep-pushdown", "Triceps")] * 3
    )
    # Triceps lead by set share: they are primary in three sets and secondary
    # in six more. Chest is primary in only three.
    assert share["Triceps (lateral)"] > share["Mid chest"]
    assert share["Front delt"] > share["Mid chest"]
    # The finer attributions the coarse model could not express at all.
    assert share["Upper traps"] > 0
    assert share["Rotator cuff"] > 0
    # Nothing this session did not touch.
    assert "Lats" not in share
    assert "Quads" not in share


def test_a_push_session_shows_no_pulling_muscles():
    """The gap is the finding: no lats, no rhomboids, no biceps."""
    share = _share(
        [("bench-press", "Chest")] * 3 + [("shoulder-press", "Shoulders")] * 3
    )
    for muscle in ("Lats", "Rhomboids", "Biceps", "Rear delt"):
        assert muscle not in share, f"{muscle} should not appear in a pure push session"
