"""Strength calculations — pure functions over plain values, no database.

Everything here is deliberately DB-free so it can be tested exhaustively and
reused by the session services, the analytics layer and the export without
three subtly different implementations drifting apart.

Two conventions run through the module:

**Kilograms are canonical.** Pounds exist only at the display edge. Storing
whatever unit the operator happened to be using makes every longitudinal query
a unit-archaeology exercise.

**A calculation that cannot be trusted says so rather than returning a
number.** ``estimate_1rm`` returns a result object with a validity flag, not a
bare float, because a 1RM "estimated" from a 25-rep set is not a weak estimate
— it is a different quantity wearing the same name. Callers that silently
coerce it to a float will at least have had to ignore something.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# Units
# --------------------------------------------------------------------------- #
KG_PER_LB = 0.45359237


def lb_to_kg(pounds: float) -> float:
    return float(pounds) * KG_PER_LB


def kg_to_lb(kilograms: float) -> float:
    return float(kilograms) / KG_PER_LB


def to_kg(value: float, unit: str) -> float:
    """Normalise an entered load to kilograms."""
    if unit and unit.lower() in {"lb", "lbs", "pound", "pounds"}:
        return lb_to_kg(value)
    return float(value)


def round_to_increment(value: float, increment: float) -> float:
    """Snap a load to something the gym can actually make.

    Progression that proposes 62.3 kg on a barbell is proposing nothing. The
    increment is per-exercise (2.5 kg barbell, 5 kg stack, 2 kg dumbbells).
    """
    if increment <= 0:
        return float(value)
    return round(float(value) / increment) * increment


# --------------------------------------------------------------------------- #
# Set classification
# --------------------------------------------------------------------------- #
#: Set types that count toward working volume. Warm-ups and technique work are
#: real training, but counting them would let a heavy warm-up ramp inflate
#: "hard sets" and make weekly volume incomparable between sessions.
WORKING_SET_TYPES = frozenset({
    "working", "top_set", "backoff", "amrap", "drop",
    "rest_pause", "myo_rep", "failure", "test",
})
NON_WORKING_SET_TYPES = frozenset({"warmup", "technique"})

#: Spelling variants seen from the legacy tracker and from other apps' exports.
#: Normalising on read is cheaper than a migration and survives future imports.
_SET_TYPE_ALIASES = {
    "warm-up": "warmup", "warm up": "warmup", "w": "warmup",
    "work": "working", "normal": "working", "": "working",
    "dropset": "drop", "drop-set": "drop",
    "restpause": "rest_pause", "rest-pause": "rest_pause",
    "myorep": "myo_rep", "myo-rep": "myo_rep",
    "topset": "top_set", "top-set": "top_set",
    "back-off": "backoff", "back off": "backoff",
}


def normalise_set_type(raw: str | None) -> str:
    key = (raw or "").strip().lower()
    return _SET_TYPE_ALIASES.get(key, key or "working")


def is_working_set(set_type: str | None) -> bool:
    return normalise_set_type(set_type) in WORKING_SET_TYPES


def is_hard_set(
    set_type: str | None,
    *,
    rpe: float | None = None,
    rir: float | None = None,
    to_failure: bool = False,
    hard_rpe: float = 7.0,
    hard_rir: float = 3.0,
) -> bool:
    """A working set taken close enough to failure to drive adaptation.

    Deliberately conservative about missing effort data: a working set with no
    RPE and no RIR is *not* assumed hard. Counting unrated sets as hard would
    make the metric track how diligently the operator rates sets rather than
    how hard they trained — and the number would quietly inflate the moment
    they stopped bothering.
    """
    if not is_working_set(set_type):
        return False
    if to_failure or normalise_set_type(set_type) == "failure":
        return True
    if rpe is not None:
        return rpe >= hard_rpe
    if rir is not None:
        return rir <= hard_rir
    return False


# --------------------------------------------------------------------------- #
# Load and volume
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SetInput:
    """One set's worth of numbers, independent of how it is stored."""

    weight_kg: float | None = None
    reps: int | None = None
    set_type: str = "working"
    load_type: str = "external"
    duration_seconds: float | None = None
    distance_m: float | None = None
    bodyweight_kg: float | None = None
    bodyweight_factor: float | None = None
    assistance_kg: float | None = None
    rpe: float | None = None
    rir: float | None = None
    to_failure: bool = False
    left_reps: int | None = None
    right_reps: int | None = None
    left_weight_kg: float | None = None
    right_weight_kg: float | None = None


#: Fraction of bodyweight a movement loads when the exercise has not specified
#: its own. Rough published estimates, not measurements — see the caveat in
#: docs/strength/calculations.md. Exposed so it can be tuned per exercise.
DEFAULT_BODYWEIGHT_FACTOR = 0.65


def effective_load_kg(s: SetInput) -> float:
    """The load actually moved by one repetition, in kilograms.

    The four load types genuinely differ, and collapsing them corrupts volume:

    - ``external``: the weight on the bar is the load.
    - ``bodyweight``: a fraction of bodyweight (a push-up is not 0 kg, which is
      what "weight" alone would record, and not full bodyweight either).
    - ``weighted_bodyweight``: that fraction plus whatever was added.
    - ``assisted``: bodyweight *minus* assistance, so a pull-up needing less
      help each week reads as progress rather than as falling volume.
    """
    load_type = (s.load_type or "external").lower()
    added = float(s.weight_kg or 0.0)

    if load_type == "external":
        return added

    bodyweight = s.bodyweight_kg
    if bodyweight is None:
        # No bodyweight recorded: fall back to the added load alone rather than
        # inventing a body mass. Zero for a plain push-up is wrong, but a made-up
        # 80 kg is wrong *and* looks authoritative.
        return added

    factor = s.bodyweight_factor
    if factor is None:
        factor = 1.0 if load_type in {"weighted_bodyweight", "assisted"} else DEFAULT_BODYWEIGHT_FACTOR
    base = float(bodyweight) * float(factor)

    if load_type == "assisted":
        return max(0.0, base - float(s.assistance_kg or 0.0))
    return base + added


def total_reps(s: SetInput) -> int:
    """Reps in the set, summing both sides when they were logged separately."""
    if s.left_reps is not None or s.right_reps is not None:
        return int(s.left_reps or 0) + int(s.right_reps or 0)
    return int(s.reps or 0)


def set_volume_kg(s: SetInput) -> float:
    """Load × reps for one set.

    Unilateral sets logged per side are summed side by side, so a set of 8 per
    arm at 20 kg is 320 kg, not 160 — the limb did the work twice.

    Duration- and distance-based sets return 0.0: a 60-second plank has no
    meaningful tonnage, and inventing one would pollute every volume total it
    lands in. Those are reported through their own measures instead.
    """
    if s.left_reps is not None or s.right_reps is not None:
        left = float(s.left_weight_kg if s.left_weight_kg is not None else (s.weight_kg or 0.0))
        right = float(s.right_weight_kg if s.right_weight_kg is not None else (s.weight_kg or 0.0))
        if (s.load_type or "external").lower() != "external":
            left = right = effective_load_kg(s)
        return left * int(s.left_reps or 0) + right * int(s.right_reps or 0)

    reps = int(s.reps or 0)
    if reps <= 0:
        return 0.0
    return effective_load_kg(s) * reps


# --------------------------------------------------------------------------- #
# Estimated one-repetition maximum
# --------------------------------------------------------------------------- #
#: Above this the formulas diverge sharply from each other and from reality —
#: they were fitted on low-rep sets. A 20-rep set says a great deal about
#: endurance and very little about a 1RM.
MAX_VALID_E1RM_REPS = 12
FORMULAS = ("epley", "brzycki", "lombardi")


@dataclass(frozen=True)
class E1RM:
    """An estimated 1RM that knows how much to trust itself."""

    value: float | None
    formula: str
    reps: int
    weight_kg: float
    valid: bool
    reason: str = ""
    #: True when reps == 1 — then it is not an estimate at all.
    measured: bool = False

    def __bool__(self) -> bool:  # `if e1rm:` should mean "usable"
        return self.valid and self.value is not None


def estimate_1rm(
    weight_kg: float | None,
    reps: int | None,
    *,
    formula: str = "epley",
    max_reps: int = MAX_VALID_E1RM_REPS,
) -> E1RM:
    """Estimate a one-rep max, or explain why it should not be estimated.

    A single rep is returned as ``measured`` rather than run through a formula:
    every formula should collapse to the lifted weight at one rep, and Epley
    notably does not (it returns 1.033×). Reporting a measured single as 3%
    heavier than it was is a small lie that compounds into a fake PR.
    """
    w = float(weight_kg or 0.0)
    r = int(reps or 0)
    formula = (formula or "epley").lower()

    if formula not in FORMULAS:
        raise ValueError(f"unknown 1RM formula: {formula!r}")
    if w <= 0 or r <= 0:
        return E1RM(None, formula, r, w, False, "no load or reps recorded")
    if r == 1:
        return E1RM(w, formula, 1, w, True, "single rep — measured, not estimated", True)
    if r > max_reps:
        return E1RM(
            None, formula, r, w, False,
            f"{r} reps is beyond the {max_reps}-rep limit where 1RM formulas hold",
        )

    if formula == "epley":
        value = w * (1.0 + r / 30.0)
    elif formula == "brzycki":
        # Denominator vanishes at 37 reps; the rep cap above keeps us far away,
        # but the guard stays so a raised cap cannot produce a division by zero.
        if r >= 37:
            return E1RM(None, formula, r, w, False, "Brzycki is undefined at 37+ reps")
        value = w * 36.0 / (37.0 - r)
    else:  # lombardi
        value = w * math.pow(r, 0.10)

    return E1RM(round(value, 2), formula, r, w, True)


def weight_for_reps(one_rm: float, reps: int, *, formula: str = "epley") -> float:
    """Invert the 1RM estimate: what load should allow ``reps`` reps?

    Used to turn a percentage prescription into a real number.
    """
    r = max(1, int(reps))
    if formula == "brzycki":
        return one_rm * (37.0 - r) / 36.0
    if formula == "lombardi":
        return one_rm / math.pow(r, 0.10)
    return one_rm / (1.0 + r / 30.0)


# --------------------------------------------------------------------------- #
# Effort scales
# --------------------------------------------------------------------------- #
def rir_to_rpe(rir: float | None) -> float | None:
    """RPE 10 = failure, so RPE ≈ 10 − RIR on the standard resistance scale."""
    if rir is None:
        return None
    return max(1.0, min(10.0, 10.0 - float(rir)))


def rpe_to_rir(rpe: float | None) -> float | None:
    if rpe is None:
        return None
    # Clamped at both ends: RIR is only defined over 0..10, and an out-of-range
    # RPE (a typo, or a foreign import on a different scale) must not produce a
    # nonsense "15 reps in reserve" that then reads as an easy set.
    return max(0.0, min(10.0, 10.0 - float(rpe)))


def intensity_band(percent_1rm: float | None) -> str:
    """Coarse load band. Thresholds are conventional, not physiological law."""
    if percent_1rm is None:
        return "unknown"
    if percent_1rm >= 0.85:
        return "heavy"
    if percent_1rm >= 0.70:
        return "moderate"
    return "light"


# --------------------------------------------------------------------------- #
# Muscle-group attribution
# --------------------------------------------------------------------------- #
#: How much of a set counts toward a secondary muscle. A convention for making
#: volume comparable, NOT a physiological claim — the docs say so, and so does
#: the UI wherever indirect volume is shown.
DEFAULT_PRIMARY_WEIGHT = 1.0
DEFAULT_SECONDARY_WEIGHT = 0.5


@dataclass(frozen=True)
class MuscleWeighting:
    primary: float = DEFAULT_PRIMARY_WEIGHT
    secondary: float = DEFAULT_SECONDARY_WEIGHT

    def as_dict(self) -> dict:
        return {"primary": self.primary, "secondary": self.secondary}


def attribute_set_to_muscles(
    primary_muscle: str,
    secondary_muscles: list[str] | None,
    *,
    weighting: MuscleWeighting | None = None,
) -> dict[str, float]:
    """Split one set across the muscles it trained.

    Returns fractional set counts, e.g. ``{"Chest": 1.0, "Triceps": 0.5}``.
    A muscle listed as both primary and secondary is counted once, at the
    primary weight, rather than 1.5 — which would otherwise happen silently on
    a mis-tagged exercise.
    """
    w = weighting or MuscleWeighting()
    out: dict[str, float] = {}
    if primary_muscle:
        out[primary_muscle] = w.primary
    for muscle in secondary_muscles or []:
        if muscle and muscle not in out:
            out[muscle] = w.secondary
    return out


# --------------------------------------------------------------------------- #
# Plate maths
# --------------------------------------------------------------------------- #
#: A standard commercial-gym set, heaviest first, in kilograms.
DEFAULT_PLATES_KG = (25.0, 20.0, 15.0, 10.0, 5.0, 2.5, 1.25)
DEFAULT_BAR_KG = 20.0


@dataclass(frozen=True)
class PlateSolution:
    target_kg: float
    bar_kg: float
    per_side: list[float] = field(default_factory=list)
    achieved_kg: float = 0.0
    exact: bool = True
    note: str = ""


def plates_for(
    target_kg: float,
    *,
    bar_kg: float = DEFAULT_BAR_KG,
    plates: tuple[float, ...] = DEFAULT_PLATES_KG,
    pairs_available: int = 10,
) -> PlateSolution:
    """Which plates to load per side to reach a target.

    Greedy heaviest-first, which is optimal for the standard doubling-ish plate
    set and is also what a lifter actually does. Reports ``exact=False`` with
    the achievable weight rather than pretending — being told to load a weight
    the plates cannot make is worse than being told the nearest one.
    """
    if target_kg < bar_kg:
        return PlateSolution(
            target_kg, bar_kg, [], bar_kg, target_kg == bar_kg,
            "target is below the empty bar",
        )

    per_side_needed = (float(target_kg) - float(bar_kg)) / 2.0
    remaining = per_side_needed
    chosen: list[float] = []
    counts = {p: 0 for p in plates}

    for plate in sorted(plates, reverse=True):
        while remaining >= plate - 1e-9 and counts[plate] < pairs_available:
            chosen.append(plate)
            counts[plate] += 1
            remaining -= plate

    achieved = bar_kg + 2 * sum(chosen)
    exact = abs(achieved - target_kg) < 1e-6
    note = "" if exact else f"nearest loadable weight is {achieved:g} kg"
    return PlateSolution(float(target_kg), float(bar_kg), chosen, achieved, exact, note)


# --------------------------------------------------------------------------- #
# Session-level aggregates
# --------------------------------------------------------------------------- #
def session_volume_kg(sets: list[SetInput], *, working_only: bool = True) -> float:
    return sum(
        set_volume_kg(s) for s in sets
        if not working_only or is_working_set(s.set_type)
    )


def count_working_sets(sets: list[SetInput]) -> int:
    return sum(1 for s in sets if is_working_set(s.set_type))


def count_hard_sets(sets: list[SetInput], **kwargs) -> int:
    return sum(
        1 for s in sets
        if is_hard_set(s.set_type, rpe=s.rpe, rir=s.rir, to_failure=s.to_failure, **kwargs)
    )


def best_e1rm(sets: list[SetInput], *, formula: str = "epley") -> E1RM | None:
    """Highest defensible 1RM estimate across a group of sets."""
    best: E1RM | None = None
    for s in sets:
        if not is_working_set(s.set_type):
            continue
        est = estimate_1rm(effective_load_kg(s), s.reps, formula=formula)
        if est and (best is None or (est.value or 0) > (best.value or 0)):
            best = est
    return best


def session_rpe_load(session_rpe: float | None, duration_minutes: float | None) -> float | None:
    """Foster session-RPE load: sRPE × minutes.

    A whole-session internal-load figure, comparable across modalities in a way
    tonnage is not. Returns None rather than 0 when either input is missing, so
    an unrated session does not read as a session with no load.
    """
    if session_rpe is None or duration_minutes is None:
        return None
    return float(session_rpe) * float(duration_minutes)
