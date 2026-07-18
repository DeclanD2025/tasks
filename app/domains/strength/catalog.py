"""The exercise library — families, variants and classification.

The 83 seeded exercises arrived with free-text movement patterns ("horizontal
pull", "plantar flexion", "fly", "power") and no notion of which exercises are
variants of each other. That is enough to log a workout and not nearly enough
to analyse one: "is my pressing getting stronger?" cannot be answered if
barbell bench, dumbbell bench and machine press are three unrelated strings.

This module adds four grouping levels, from most to least specific:

1. **Exercise** — barbell bench press. Loads are directly comparable.
2. **Family** — the bench-press family. Variants of one movement; loads are
   *not* comparable across them, but trend direction is.
3. **Movement pattern** — horizontal push. Pull-ups and lat pulldowns live in
   different families but answer the same question about vertical pulling.
4. **Muscle group** — chest. Volume aggregates here.

Classification is applied idempotently to existing rows, so it can be re-run
after the table is edited without clobbering the operator's own exercises.
"""

from __future__ import annotations

import re

from sqlalchemy import select

from app.db.database import session_scope
from app.db.models import StrengthExercise
from app.core.logging import get_logger

log = get_logger(__name__)


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")


# --------------------------------------------------------------------------- #
# Movement patterns
# --------------------------------------------------------------------------- #
#: Free-text patterns from the seed → the canonical vocabulary in models.py.
#: Anything unmapped falls through to "other" rather than being invented, so a
#: new exercise cannot quietly join the wrong movement rollup.
_MOVEMENT_MAP = {
    "horizontal push": "horizontal_push",
    "incline push": "horizontal_push",  # closer to horizontal than overhead
    "vertical push": "vertical_push",
    "press": "vertical_push",
    "horizontal pull": "horizontal_pull",
    "row": "horizontal_pull",
    "vertical pull": "vertical_pull",
    "pull": "vertical_pull",
    "shoulder extension": "vertical_pull",
    "squat": "squat",
    "hinge": "hinge",
    "hip extension": "hinge",
    "lunge": "lunge",
    "carry": "carry",
    "elbow flexion": "elbow_flexion",
    "elbow extension": "elbow_extension",
    "knee flexion": "knee_flexion",
    "knee extension": "knee_extension",
    "plantar flexion": "calf",
    "spinal flexion": "core_flexion",
    "hip flexion": "core_flexion",
    "anti-extension": "anti_extension",
    "anti-rotation": "anti_rotation",
    "rotation": "rotation",
    "fly": "horizontal_push",
    "horizontal abduction": "horizontal_pull",
    "abduction": "other",
    "external rotation": "other",
    "elevation": "other",
    "power": "other",
}


def normalise_movement(raw: str | None) -> str:
    key = (raw or "").strip().lower().replace("_", " ")
    return _MOVEMENT_MAP.get(key, "other")


# --------------------------------------------------------------------------- #
# Families
# --------------------------------------------------------------------------- #
#: Exercises that are variants of one movement. Anything not listed becomes its
#: own family (family_slug == slug), which is the honest default: an exercise
#: with no stated relatives should not be silently pooled with anything.
#:
#: Judgement calls worth stating:
#: - Incline pressing is a separate family from flat. The angle changes the
#:   movement enough that pooling their loads would mask a real difference.
#: - Pull-ups and lat pulldowns are separate families — one is bodyweight, one
#:   is external load, so their numbers mean different things. They still meet
#:   at the vertical_pull movement level, which is the right place for it.
#: - Leg press is not in the squat family for the same reason.
_FAMILIES: dict[str, tuple[str, ...]] = {
    "bench-press": (
        "bench-press", "dumbbell-bench-press", "smith-machine-bench-press",
        "chest-press-machine", "close-grip-bench-press", "push-up",
    ),
    "incline-press": ("incline-bench-press", "incline-dumbbell-press"),
    "chest-fly": ("cable-fly", "low-cable-fly", "pec-deck"),
    "squat": ("squat", "front-squat", "goblet-squat", "hack-squat", "smith-machine-squat"),
    "deadlift": ("deadlift",),
    "romanian-deadlift": ("romanian-deadlift", "dumbbell-romanian-deadlift"),
    "overhead-press": (
        "shoulder-press", "dumbbell-shoulder-press", "machine-shoulder-press",
        "arnold-press", "landmine-press",
    ),
    "row": (
        "barbell-row", "dumbbell-row", "seated-cable-row", "machine-row",
        "chest-supported-row", "t-bar-row", "single-arm-cable-row", "landmine-row",
    ),
    "pull-up": ("pull-up", "chin-up"),
    "lat-pulldown": ("lat-pulldown",),
    "dip": ("dip", "tricep-dip"),
    "biceps-curl": (
        "bicep-curl", "cable-curl", "ez-bar-curl", "hammer-curl",
        "incline-dumbbell-curl", "preacher-curl", "concentration-curl",
    ),
    "triceps-extension": (
        "rope-pushdown", "tricep-pushdown", "cable-overhead-extension",
        "overhead-tricep-extension", "skullcrusher",
    ),
    "lateral-raise": ("lateral-raise", "cable-lateral-raise"),
    "rear-delt-fly": ("rear-delt-fly", "reverse-pec-deck"),
    "leg-curl": ("leg-curl", "seated-leg-curl"),
    "leg-extension": ("leg-extension",),
    "leg-press": ("leg-press",),
    "calf-raise": ("calf-raise", "seated-calf-raise", "standing-calf-raise"),
    "hip-thrust": ("hip-thrust", "glute-bridge"),
    "lunge": ("walking-lunge", "step-up", "bulgarian-split-squat"),
}

_FAMILY_BY_SLUG: dict[str, str] = {
    slug: family for family, slugs in _FAMILIES.items() for slug in slugs
}


def family_for(slug: str) -> str:
    """Which family an exercise belongs to. Its own slug when it stands alone."""
    return _FAMILY_BY_SLUG.get(slug, slug)


# --------------------------------------------------------------------------- #
# Load type, measurement and increments
# --------------------------------------------------------------------------- #
#: Exercises measured in time or distance rather than repetitions. Recording a
#: plank as reps is not a rounding error, it is the wrong quantity.
_DURATION_EXERCISES = frozenset({"plank"})
_DISTANCE_EXERCISES = frozenset({"farmer-carry", "sled-push"})

#: Bodyweight movements that can also be loaded or assisted. Their default is
#: bodyweight; the session resolves the actual type per set from what was
#: entered (added weight → weighted, assistance → assisted).
_LOADABLE_BODYWEIGHT = frozenset({"pull-up", "chin-up", "dip", "tricep-dip"})

#: Roughly what fraction of bodyweight each movement actually loads. Published
#: estimates, not measurements — surfaced as such wherever they are used.
_BODYWEIGHT_FACTORS = {
    "push-up": 0.64,
    "pull-up": 1.0,
    "chin-up": 1.0,
    "dip": 1.0,
    "tricep-dip": 1.0,
    "hanging-leg-raise": 0.5,
    "ab-wheel-rollout": 0.6,
    "back-extension": 0.55,
    "plank": 0.6,
}

#: Smallest usable jump by equipment. A stack machine cannot do 2.5 kg, and
#: proposing it makes the progression engine look broken.
_INCREMENTS = {
    "Barbell": 2.5,
    "Smith machine": 2.5,
    "Plate loaded": 2.5,
    "Dumbbell": 2.0,
    "Kettlebell": 4.0,
    "Machine": 5.0,
    "Cable": 2.5,
    "Bodyweight": 1.25,
}

_BAR_WEIGHTS = {"Barbell": 20.0, "Smith machine": 15.0}

#: Multi-joint movements. Drives indirect-volume attribution and the
#: compound-first ordering hint in the programme builder.
_ISOLATION_PATTERNS = frozenset({
    "elbow_flexion", "elbow_extension", "knee_flexion", "knee_extension",
    "calf", "core_flexion", "anti_extension", "anti_rotation", "rotation",
})


def classify(
    *,
    name: str,
    slug: str = "",
    primary_muscle: str = "",
    equipment: str = "",
    movement_pattern: str = "",
    unilateral: bool = False,
) -> dict:
    """Derive the full classification for one exercise.

    Pure — takes and returns plain values — so the seeder, the custom-exercise
    creator and the tests all agree by construction rather than by discipline.
    """
    slug = slug or slugify(name)
    movement = normalise_movement(movement_pattern)

    if slug in _DURATION_EXERCISES:
        measurement = "duration"
    elif slug in _DISTANCE_EXERCISES:
        measurement = "distance"
    else:
        measurement = "reps"

    if equipment == "Bodyweight":
        load_type = "bodyweight"
    else:
        load_type = "external"

    return {
        "slug": slug,
        "family_slug": family_for(slug),
        "movement_pattern": movement,
        "measurement": measurement,
        "load_type": load_type,
        "laterality": "unilateral_separate" if unilateral else "bilateral",
        "is_compound": movement not in _ISOLATION_PATTERNS,
        "increment_kg": _INCREMENTS.get(equipment, 2.5),
        "bar_weight_kg": _BAR_WEIGHTS.get(equipment),
        "tracking_config": {
            "bodyweight_factor": _BODYWEIGHT_FACTORS.get(slug),
            "loadable": slug in _LOADABLE_BODYWEIGHT,
        },
    }


def resolve_load_type(
    exercise_load_type: str,
    *,
    weight_kg: float | None = None,
    assistance_kg: float | None = None,
) -> str:
    """What load type a *specific set* was actually performed under.

    A pull-up exercise is classified ``bodyweight``, but the set where a 20 kg
    belt went on is ``weighted_bodyweight``, and the set done on the assist
    machine is ``assisted``. Resolving per set is what lets one exercise hold a
    continuous history across a lifter's whole progression from assisted to
    weighted — which is exactly the arc worth being able to see.
    """
    base = (exercise_load_type or "external").lower()
    if base != "bodyweight":
        return base
    if assistance_kg:
        return "assisted"
    if weight_kg:
        return "weighted_bodyweight"
    return "bodyweight"


# --------------------------------------------------------------------------- #
# Applying classification to stored exercises
# --------------------------------------------------------------------------- #
def enrich_catalog(*, force: bool = False) -> int:
    """Backfill classification onto exercises that lack it.

    Idempotent and conservative: by default it only fills a field that is still
    at its default, so an exercise the operator has hand-corrected is not
    reverted on the next deploy. ``force=True`` reapplies everything, which is
    what to use after editing the tables above.
    """
    updated = 0
    with session_scope() as s:
        for ex in s.scalars(select(StrengthExercise)).all():
            facts = classify(
                name=ex.name,
                slug=ex.slug,
                primary_muscle=ex.primary_muscle,
                equipment=ex.equipment,
                movement_pattern=ex.movement_pattern,
                unilateral=bool(ex.unilateral),
            )
            changed = False

            if force or not ex.family_slug:
                if ex.family_slug != facts["family_slug"]:
                    ex.family_slug = facts["family_slug"]
                    changed = True
            # The seeded movement patterns are free text; normalising them is
            # the whole point, so this one overwrites unless already canonical.
            if force or ex.movement_pattern != facts["movement_pattern"]:
                if "_" not in (ex.movement_pattern or "") or force:
                    ex.movement_pattern = facts["movement_pattern"]
                    changed = True
            for field in ("measurement", "load_type", "laterality"):
                default = {"measurement": "reps", "load_type": "external",
                           "laterality": "bilateral"}[field]
                if force or getattr(ex, field, default) == default:
                    if getattr(ex, field) != facts[field]:
                        setattr(ex, field, facts[field])
                        changed = True
            if force or not ex.is_compound:
                if ex.is_compound != facts["is_compound"]:
                    ex.is_compound = facts["is_compound"]
                    changed = True
            if force or ex.increment_kg == 2.5:
                if ex.increment_kg != facts["increment_kg"]:
                    ex.increment_kg = facts["increment_kg"]
                    changed = True
            if force or ex.bar_weight_kg is None:
                if ex.bar_weight_kg != facts["bar_weight_kg"]:
                    ex.bar_weight_kg = facts["bar_weight_kg"]
                    changed = True
            if force or not ex.tracking_config:
                ex.tracking_config = facts["tracking_config"]
                changed = True

            if changed:
                updated += 1
    if updated:
        log.info("Classified %d strength exercises.", updated)
    return updated


def bodyweight_factor_for(exercise: StrengthExercise) -> float | None:
    """The exercise's own bodyweight fraction, if it has one."""
    return (exercise.tracking_config or {}).get("bodyweight_factor")
