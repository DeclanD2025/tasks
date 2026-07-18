"""Detailed muscle anatomy and per-exercise attribution.

The seeded catalogue tags each exercise with one coarse muscle group — "Chest",
"Shoulders", "Back". That is enough to colour an icon and useless for asking
whether your side delts are actually getting trained. "Shoulders" lumps front,
side and rear delts, which respond to completely different movements; "Back"
lumps lats with traps with erectors.

This module replaces that with a 27-muscle model and a three-tier contribution
map per exercise:

    primary      the muscle the movement is for
    secondary    a significant synergist doing real work
    stabiliser   holding position isometrically, or assisting slightly

**These are a mapping convention, not a measurement.** Nobody has put Declan in
an EMG lab. The tiers encode consensus about which muscles a movement trains,
weighted so that volume is comparable between exercises — and every surface
that shows the resulting numbers says so. The weights are configurable
precisely because they are conventions rather than constants.

The stabiliser tier is what makes a bench press correctly show a little rotator
cuff and upper trap involvement, rather than pretending the movement is chest
and triceps alone.
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# Anatomy
# --------------------------------------------------------------------------- #
#: Muscle → region, for rollups. Regions keep a 27-row chart readable.
REGIONS: dict[str, str] = {
    # Chest — the clavicular head genuinely responds to incline work
    # differently, which is why it is split and "Chest" is not.
    "Upper chest": "Chest",
    "Mid chest": "Chest",
    # Back
    "Lats": "Back",
    "Upper traps": "Back",
    "Mid/lower traps": "Back",
    "Rhomboids": "Back",
    "Erectors": "Back",
    "Teres major": "Back",
    # Shoulders — three heads that share a name and almost nothing else.
    "Front delt": "Shoulders",
    "Side delt": "Shoulders",
    "Rear delt": "Shoulders",
    "Rotator cuff": "Shoulders",
    # Arms — triceps split by head because overhead and pushdown work bias
    # them differently, which is a distinction lifters program around.
    "Biceps": "Arms",
    "Brachialis": "Arms",
    "Triceps (long head)": "Arms",
    "Triceps (lateral)": "Arms",
    "Forearms": "Arms",
    # Legs
    "Quads": "Legs",
    "Hamstrings": "Legs",
    "Glute max": "Legs",
    "Glute med": "Legs",
    "Adductors": "Legs",
    "Gastrocnemius": "Legs",
    "Soleus": "Legs",
    "Hip flexors": "Legs",
    # Core
    "Rectus abdominis": "Core",
    "Obliques": "Core",
    "Deep core": "Core",
}

REGION_ORDER = ("Chest", "Back", "Shoulders", "Arms", "Legs", "Core")

ALL_MUSCLES = tuple(REGIONS)


def region_for(muscle: str) -> str:
    return REGIONS.get(muscle, "Other")


# --------------------------------------------------------------------------- #
# Exercise → muscles
# --------------------------------------------------------------------------- #
# (primary, secondary, stabiliser) keyed by exercise slug.
#
# Compiled from movement mechanics rather than from any single source. Where a
# call was genuinely arguable it is noted. Anything not listed falls back to the
# coarse `primary_muscle` from the seed, so an exercise added later degrades to
# the old behaviour instead of silently attributing to nothing.
MUSCLE_MAP: dict[str, tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = {
    # --- Chest ---------------------------------------------------------- #
    "bench-press": (
        ("Mid chest",),
        ("Front delt", "Triceps (lateral)"),
        ("Upper chest", "Rotator cuff", "Upper traps"),
    ),
    "incline-bench-press": (
        ("Upper chest",),
        ("Front delt", "Triceps (lateral)"),
        ("Mid chest", "Rotator cuff", "Upper traps"),
    ),
    "dumbbell-bench-press": (
        ("Mid chest",),
        ("Front delt", "Triceps (lateral)"),
        ("Upper chest", "Rotator cuff"),
    ),
    "incline-dumbbell-press": (
        ("Upper chest",),
        ("Front delt", "Triceps (lateral)"),
        ("Mid chest", "Rotator cuff"),
    ),
    "smith-machine-bench-press": (
        ("Mid chest",), ("Front delt", "Triceps (lateral)"), ("Upper chest",),
    ),
    "chest-press-machine": (
        ("Mid chest",), ("Front delt", "Triceps (lateral)"), ("Upper chest",),
    ),
    "push-up": (
        ("Mid chest",),
        ("Front delt", "Triceps (lateral)"),
        ("Rectus abdominis", "Deep core", "Rotator cuff"),
    ),
    "dip": (
        ("Mid chest",),
        ("Triceps (lateral)", "Front delt"),
        ("Rotator cuff", "Rectus abdominis"),
    ),
    "cable-fly": (("Mid chest",), ("Front delt",), ("Rotator cuff",)),
    "low-cable-fly": (("Upper chest",), ("Front delt",), ("Rotator cuff",)),
    "pec-deck": (("Mid chest",), ("Front delt",), ()),

    # --- Back ----------------------------------------------------------- #
    "barbell-row": (
        ("Lats", "Rhomboids", "Mid/lower traps"),
        ("Rear delt", "Biceps", "Brachialis"),
        ("Erectors", "Forearms", "Deep core"),
    ),
    "t-bar-row": (
        ("Lats", "Rhomboids", "Mid/lower traps"),
        ("Rear delt", "Biceps"),
        ("Erectors", "Forearms"),
    ),
    "dumbbell-row": (
        ("Lats", "Rhomboids"),
        ("Mid/lower traps", "Biceps", "Rear delt"),
        ("Erectors", "Forearms", "Obliques"),
    ),
    "chest-supported-row": (
        ("Lats", "Rhomboids", "Mid/lower traps"), ("Rear delt", "Biceps"), ("Forearms",),
    ),
    "machine-row": (
        ("Lats", "Rhomboids"), ("Mid/lower traps", "Biceps", "Rear delt"), ("Forearms",),
    ),
    "seated-cable-row": (
        ("Lats", "Rhomboids", "Mid/lower traps"),
        ("Biceps", "Rear delt"),
        ("Erectors", "Forearms"),
    ),
    "single-arm-cable-row": (
        ("Lats", "Rhomboids"), ("Biceps", "Rear delt"), ("Obliques", "Forearms"),
    ),
    "landmine-row": (
        ("Lats", "Rhomboids"), ("Mid/lower traps", "Biceps", "Rear delt"), ("Erectors",),
    ),
    "pull-up": (
        ("Lats",),
        ("Teres major", "Biceps", "Brachialis", "Rhomboids"),
        ("Rectus abdominis", "Forearms", "Mid/lower traps"),
    ),
    "chin-up": (
        ("Lats",),
        ("Biceps", "Brachialis", "Teres major"),
        ("Rectus abdominis", "Forearms", "Rhomboids"),
    ),
    "lat-pulldown": (
        ("Lats",),
        ("Biceps", "Brachialis", "Teres major", "Rhomboids"),
        ("Forearms", "Mid/lower traps"),
    ),
    "straight-arm-pulldown": (
        ("Lats",), ("Teres major", "Triceps (long head)"), ("Rectus abdominis",),
    ),

    # --- Shoulders ------------------------------------------------------ #
    "shoulder-press": (
        ("Front delt",),
        ("Side delt", "Triceps (lateral)", "Upper traps"),
        ("Rotator cuff", "Deep core", "Erectors"),
    ),
    "dumbbell-shoulder-press": (
        ("Front delt",),
        ("Side delt", "Triceps (lateral)", "Upper traps"),
        ("Rotator cuff", "Deep core"),
    ),
    "machine-shoulder-press": (
        ("Front delt",), ("Side delt", "Triceps (lateral)"), ("Upper traps", "Rotator cuff"),
    ),
    "arnold-press": (
        ("Front delt", "Side delt"),
        ("Triceps (lateral)", "Upper traps"),
        ("Rotator cuff", "Deep core"),
    ),
    "landmine-press": (
        ("Front delt",), ("Upper chest", "Triceps (lateral)"), ("Deep core", "Obliques"),
    ),
    "lateral-raise": (("Side delt",), ("Upper traps",), ("Rotator cuff",)),
    "cable-lateral-raise": (("Side delt",), ("Upper traps",), ("Rotator cuff",)),
    "rear-delt-fly": (("Rear delt",), ("Rhomboids", "Mid/lower traps"), ("Rotator cuff",)),
    "reverse-pec-deck": (("Rear delt",), ("Rhomboids", "Mid/lower traps"), ()),
    "face-pull": (
        ("Rear delt",), ("Rotator cuff", "Mid/lower traps", "Rhomboids"), (),
    ),
    "shrug": (("Upper traps",), ("Mid/lower traps",), ("Forearms",)),
    "upright-row": (
        ("Side delt", "Upper traps"), ("Biceps", "Brachialis"), ("Rotator cuff",),
    ),

    # --- Arms ----------------------------------------------------------- #
    "bicep-curl": (("Biceps",), ("Brachialis",), ("Forearms",)),
    "cable-curl": (("Biceps",), ("Brachialis",), ("Forearms",)),
    "ez-bar-curl": (("Biceps",), ("Brachialis",), ("Forearms",)),
    "preacher-curl": (("Biceps",), ("Brachialis",), ()),
    "concentration-curl": (("Biceps",), ("Brachialis",), ()),
    # Incline curls put the long head under stretch; still biceps-primary.
    "incline-dumbbell-curl": (("Biceps",), ("Brachialis",), ("Forearms",)),
    # Hammer curls are brachialis-led, which is why they are not just "biceps".
    "hammer-curl": (("Brachialis", "Biceps"), ("Forearms",), ()),
    "tricep-pushdown": (("Triceps (lateral)",), ("Triceps (long head)",), ()),
    "rope-pushdown": (("Triceps (lateral)",), ("Triceps (long head)",), ()),
    "overhead-tricep-extension": (
        ("Triceps (long head)",), ("Triceps (lateral)",), ("Deep core",),
    ),
    "cable-overhead-extension": (
        ("Triceps (long head)",), ("Triceps (lateral)",), ("Deep core",),
    ),
    "skullcrusher": (("Triceps (long head)",), ("Triceps (lateral)",), ()),
    "close-grip-bench-press": (
        ("Triceps (lateral)",),
        ("Mid chest", "Front delt"),
        ("Triceps (long head)", "Rotator cuff"),
    ),
    "tricep-dip": (
        ("Triceps (lateral)",), ("Mid chest", "Front delt"), ("Rotator cuff",),
    ),

    # --- Legs ----------------------------------------------------------- #
    "squat": (
        ("Quads", "Glute max"),
        ("Erectors", "Adductors"),
        ("Hamstrings", "Deep core", "Upper traps"),
    ),
    "front-squat": (
        ("Quads",), ("Glute max", "Erectors"), ("Deep core", "Upper traps", "Adductors"),
    ),
    "hack-squat": (("Quads",), ("Glute max",), ("Adductors",)),
    "smith-machine-squat": (("Quads",), ("Glute max",), ("Adductors", "Erectors")),
    "goblet-squat": (("Quads",), ("Glute max",), ("Deep core", "Front delt", "Adductors")),
    "leg-press": (("Quads",), ("Glute max",), ("Adductors", "Hamstrings")),
    "leg-extension": (("Quads",), (), ()),
    "walking-lunge": (
        ("Quads", "Glute max"), ("Hamstrings", "Adductors"), ("Glute med", "Deep core"),
    ),
    "bulgarian-split-squat": (
        ("Quads", "Glute max"), ("Hamstrings", "Adductors"), ("Glute med", "Deep core"),
    ),
    "step-up": (("Quads", "Glute max"), ("Hamstrings",), ("Glute med", "Deep core")),
    "deadlift": (
        ("Hamstrings", "Glute max", "Erectors"),
        ("Quads", "Lats", "Upper traps"),
        ("Forearms", "Deep core", "Rhomboids"),
    ),
    "romanian-deadlift": (
        ("Hamstrings",), ("Glute max", "Erectors"), ("Forearms", "Lats", "Deep core"),
    ),
    "dumbbell-romanian-deadlift": (
        ("Hamstrings",), ("Glute max", "Erectors"), ("Forearms", "Deep core"),
    ),
    "good-morning": (("Hamstrings", "Erectors"), ("Glute max",), ("Deep core",)),
    "back-extension": (("Erectors", "Glute max"), ("Hamstrings",), ("Deep core",)),
    "leg-curl": (("Hamstrings",), ("Gastrocnemius",), ()),
    "seated-leg-curl": (("Hamstrings",), ("Gastrocnemius",), ()),
    "hip-thrust": (("Glute max",), ("Hamstrings",), ("Quads", "Deep core", "Erectors")),
    "glute-bridge": (("Glute max",), ("Hamstrings",), ("Erectors", "Deep core")),
    "cable-kickback": (("Glute max",), ("Hamstrings",), ("Erectors",)),
    # Standing calf work is knee-extended, biasing gastrocnemius; seated is
    # knee-flexed, biasing soleus. This is the whole reason both exist.
    "calf-raise": (("Gastrocnemius",), ("Soleus",), ()),
    "standing-calf-raise": (("Gastrocnemius",), ("Soleus",), ()),
    "seated-calf-raise": (("Soleus",), ("Gastrocnemius",), ()),

    # --- Core ----------------------------------------------------------- #
    "plank": (
        ("Deep core", "Rectus abdominis"), ("Obliques",), ("Front delt", "Glute max"),
    ),
    "ab-wheel-rollout": (
        ("Deep core", "Rectus abdominis"), ("Lats", "Hip flexors"), ("Erectors",),
    ),
    "cable-crunch": (("Rectus abdominis",), ("Obliques",), ()),
    "hanging-leg-raise": (
        ("Hip flexors", "Rectus abdominis"), ("Obliques",), ("Forearms", "Lats"),
    ),
    "pallof-press": (("Deep core", "Obliques"), ("Rectus abdominis",), ("Front delt",)),
    "russian-twist": (("Obliques",), ("Rectus abdominis",), ("Hip flexors",)),

    # --- Full body ------------------------------------------------------ #
    "power-clean": (
        ("Quads", "Glute max", "Hamstrings"),
        ("Erectors", "Upper traps"),
        ("Deep core", "Forearms", "Side delt"),
    ),
    "clean-and-press": (
        ("Quads", "Glute max", "Front delt"),
        ("Erectors", "Upper traps", "Hamstrings", "Triceps (lateral)"),
        ("Deep core", "Forearms"),
    ),
    "kettlebell-swing": (
        ("Glute max", "Hamstrings"), ("Erectors", "Deep core"), ("Forearms", "Quads"),
    ),
    "farmer-carry": (
        ("Forearms", "Upper traps"),
        ("Deep core", "Obliques"),
        ("Erectors", "Glute med", "Quads"),
    ),
    "sled-push": (
        ("Quads", "Glute max"),
        ("Gastrocnemius", "Hamstrings"),
        ("Deep core", "Front delt"),
    ),
}

#: Coarse group → a sensible detailed muscle, for exercises with no entry above
#: (custom ones the operator creates). Degrading to one detailed muscle beats
#: attributing to nothing.
_COARSE_FALLBACK = {
    "Chest": "Mid chest",
    "Back": "Lats",
    "Shoulders": "Front delt",
    "Biceps": "Biceps",
    "Triceps": "Triceps (lateral)",
    "Quads": "Quads",
    "Hamstrings": "Hamstrings",
    "Glutes": "Glute max",
    "Calves": "Gastrocnemius",
    "Core": "Rectus abdominis",
    "Full body": "Quads",
}


def attribution_for(slug: str, coarse_primary: str = "") -> dict:
    """The three tiers for one exercise.

    Returns ``{"primary": [...], "secondary": [...], "stabiliser": [...]}``.
    An unmapped exercise falls back to a single primary derived from its coarse
    group, so custom exercises still land somewhere real.
    """
    entry = MUSCLE_MAP.get(slug)
    if entry is not None:
        primary, secondary, stabiliser = entry
        return {
            "primary": list(primary),
            "secondary": list(secondary),
            "stabiliser": list(stabiliser),
        }
    fallback = _COARSE_FALLBACK.get(coarse_primary)
    return {
        "primary": [fallback] if fallback else [],
        "secondary": [],
        "stabiliser": [],
        "inferred": True,
    }
