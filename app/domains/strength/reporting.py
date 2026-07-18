"""Longitudinal analytics over completed strength work.

Named ``reporting`` rather than ``analytics`` for a boring but load-bearing
reason: the legacy tracker exports a function called ``analytics()``, which the
Jinja route calls as ``strength.analytics()``. A submodule of the same name is
shadowed by that function at package level, so importing it would silently hand
callers the wrong object. Renaming this module was cheaper and safer than
renaming a working legacy surface. Do not "fix" it back.


Everything here runs in the backend and returns finished numbers. None of it
belongs in a React component: these are aggregates over the operator's whole
history, they need the same definitions the records and progression engines
use, and recomputing them per render would make every definition a place for
two implementations to drift apart.

The module is opinionated about honesty in three ways:

**Warm-ups never contaminate working statistics.** Every aggregate starts from
the same filtered set list, so there is one definition of "a set that counted".

**Correlations are gated on sample size and named as associations.** With a
handful of sessions there is nothing to say, and the right output is a stated
refusal rather than a confident-looking coefficient over n=4.

**A plateau requires repeated comparable exposures.** Two unchanged sessions is
a fortnight, not a plateau, and telling someone they have stalled on that
evidence is how a useful signal becomes noise the operator learns to ignore.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.db.database import session_scope
from app.db.models import (
    StrengthExercise,
    StrengthPlannedSession,
    StrengthSetEntry,
    StrengthWorkout,
    StrengthWorkoutExercise,
)
from app.domains.strength import calc, catalog, muscles

#: Minimum paired observations before any association is reported. Below this
#: a correlation is a coin flip with a decimal point.
MIN_CORRELATION_N = 8
#: Comparable exposures required before calling a lift plateaued.
MIN_PLATEAU_SESSIONS = 4

COUNTED_STATUSES = ("completed", "partial", "abandoned")


@dataclass
class SetRecord:
    """One counted set, flattened with everything the aggregates need."""

    workout_id: int
    day: date
    started_at: datetime
    exercise_id: int
    exercise_name: str
    family_slug: str
    movement_pattern: str
    primary_muscle: str
    secondary_muscles: list[str]
    #: {"primary": [...], "secondary": [...], "stabiliser": [...]} from the
    #: detailed anatomy model.
    muscle_attribution: dict
    is_compound: bool
    set_type: str
    weight_kg: float
    reps: int
    volume_kg: float
    e1rm: float | None
    rpe: float | None
    rir: float | None
    to_failure: bool
    is_hard: bool
    duration_seconds: float | None


def _load_sets(
    user_id: int,
    *,
    since: date | None = None,
    until: date | None = None,
    exercise_id: int | None = None,
    use_snapshot_classification: bool = True,
) -> list[SetRecord]:
    """Every counted set in a window.

    ``use_snapshot_classification`` chooses which reading of history to use.
    True gives "what I believed at the time" — the classification frozen onto
    the session. False re-reads today's classification, which is what to use
    when comparing across a reclassification. Both are legitimate; silently
    picking one is not, which is why it is a parameter.
    """
    with session_scope() as s:
        query = (
            select(StrengthSetEntry, StrengthWorkout, StrengthWorkoutExercise, StrengthExercise)
            .join(
                StrengthWorkoutExercise,
                StrengthSetEntry.workout_exercise_id == StrengthWorkoutExercise.id,
            )
            .join(StrengthWorkout, StrengthWorkoutExercise.workout_id == StrengthWorkout.id)
            .join(StrengthExercise, StrengthWorkoutExercise.exercise_id == StrengthExercise.id)
            .where(
                StrengthWorkout.user_id == user_id,
                StrengthSetEntry.completed.is_(True),
                StrengthSetEntry.voided_at.is_(None),
                StrengthWorkout.status.in_(COUNTED_STATUSES),
            )
        )
        if since is not None:
            query = query.where(StrengthWorkout.started_at >= datetime.combine(since, datetime.min.time()))
        if until is not None:
            query = query.where(StrengthWorkout.started_at <= datetime.combine(until, datetime.max.time()))
        if exercise_id is not None:
            query = query.where(StrengthWorkoutExercise.exercise_id == exercise_id)

        rows = s.execute(query.order_by(StrengthWorkout.started_at)).all()

        out: list[SetRecord] = []
        for entry, workout, block, exercise in rows:
            if not calc.is_working_set(entry.set_type):
                continue
            snapshot = (block.classification_snapshot or {}) if use_snapshot_classification else {}
            load_type = catalog.resolve_load_type(
                snapshot.get("loadType", exercise.load_type),
                weight_kg=entry.weight_kg,
                assistance_kg=entry.assistance_kg,
            )
            si = calc.SetInput(
                weight_kg=entry.weight_kg,
                reps=entry.reps,
                set_type=entry.set_type,
                load_type=load_type,
                duration_seconds=entry.duration_seconds,
                bodyweight_kg=entry.bodyweight_kg,
                bodyweight_factor=entry.bodyweight_factor,
                assistance_kg=entry.assistance_kg,
                rpe=entry.rpe,
                rir=entry.rir,
                to_failure=bool(entry.to_failure),
                left_reps=entry.left_reps,
                right_reps=entry.right_reps,
                left_weight_kg=entry.left_weight_kg,
                right_weight_kg=entry.right_weight_kg,
                limb_multiplier=catalog.limb_multiplier_for(exercise),
            )
            load = calc.effective_load_kg(si)
            est = calc.estimate_1rm(load, entry.reps)
            out.append(
                SetRecord(
                    workout_id=workout.id,
                    day=workout.started_at.date(),
                    started_at=workout.started_at,
                    exercise_id=exercise.id,
                    exercise_name=exercise.display_name or exercise.name,
                    family_slug=snapshot.get("familySlug") or exercise.family_slug,
                    movement_pattern=snapshot.get("movementPattern") or exercise.movement_pattern,
                    primary_muscle=snapshot.get("primaryMuscle") or exercise.primary_muscle,
                    secondary_muscles=list(
                        snapshot.get("secondaryMuscles") or exercise.secondary_muscles or []
                    ),
                    # Prefer the snapshot when a session recorded one, so a
                    # later change to the anatomy map does not restate history.
                    # Sessions logged before the detailed model existed fall
                    # back to today's map rather than losing their attribution.
                    muscle_attribution=(
                        snapshot.get("muscleAttribution")
                        or muscles.attribution_for(exercise.slug, exercise.primary_muscle)
                    ),
                    is_compound=bool(snapshot.get("isCompound", exercise.is_compound)),
                    set_type=calc.normalise_set_type(entry.set_type),
                    weight_kg=load,
                    reps=calc.total_reps(si),
                    volume_kg=calc.set_volume_kg(si),
                    e1rm=est.value if est else None,
                    rpe=entry.rpe,
                    rir=entry.rir,
                    to_failure=bool(entry.to_failure),
                    is_hard=calc.is_hard_set(
                        entry.set_type, rpe=entry.rpe, rir=entry.rir,
                        to_failure=bool(entry.to_failure),
                    ),
                    duration_seconds=entry.duration_seconds,
                )
            )
        return out


# --------------------------------------------------------------------------- #
# Volume
# --------------------------------------------------------------------------- #
def volume_summary(sets: list[SetRecord]) -> dict:
    """Headline totals. Tonnage is reported but never called quality."""
    return {
        "volumeKg": round(sum(s.volume_kg for s in sets), 1),
        "workingSets": len(sets),
        "hardSets": sum(1 for s in sets if s.is_hard),
        "reps": sum(s.reps for s in sets),
        "sessions": len({s.workout_id for s in sets}),
        "ratedSets": sum(1 for s in sets if s.rpe is not None or s.rir is not None),
    }


def volume_by_period(sets: list[SetRecord], *, period: str = "week") -> list[dict]:
    """Volume bucketed by ISO week or calendar month."""
    buckets: dict[str, list[SetRecord]] = defaultdict(list)
    for s in sets:
        if period == "month":
            key = s.day.strftime("%Y-%m")
        else:
            iso = s.day.isocalendar()
            key = f"{iso.year}-W{iso.week:02d}"
        buckets[key].append(s)
    return [
        {"period": key, **volume_summary(rows)}
        for key, rows in sorted(buckets.items())
    ]


def _group_volume(sets: list[SetRecord], key) -> list[dict]:
    buckets: dict[str, list[SetRecord]] = defaultdict(list)
    for s in sets:
        buckets[key(s)].append(s)
    rows = [
        {
            "key": name,
            "volumeKg": round(sum(x.volume_kg for x in group), 1),
            "sets": len(group),
            "hardSets": sum(1 for x in group if x.is_hard),
            "sessions": len({x.workout_id for x in group}),
        }
        for name, group in buckets.items()
        if name
    ]
    return sorted(rows, key=lambda r: r["volumeKg"], reverse=True)


def volume_by_exercise(sets: list[SetRecord]) -> list[dict]:
    return _group_volume(sets, lambda s: s.exercise_name)


def volume_by_movement(sets: list[SetRecord]) -> list[dict]:
    return _group_volume(sets, lambda s: s.movement_pattern)


def volume_by_family(sets: list[SetRecord]) -> list[dict]:
    return _group_volume(sets, lambda s: s.family_slug)


def muscle_volume(
    sets: list[SetRecord], *, weighting: calc.MuscleWeighting | None = None
) -> list[dict]:
    """Set counts per muscle, split into direct and indirect.

    Direct and indirect are reported separately rather than summed, because
    the indirect weighting is a convention for comparability and not a
    physiological measurement. Anyone reading the number deserves to see how
    much of it is inference.
    """
    w = weighting or calc.MuscleWeighting()
    direct: dict[str, float] = defaultdict(float)
    indirect: dict[str, float] = defaultdict(float)
    volume: dict[str, float] = defaultdict(float)
    last_trained: dict[str, date] = {}
    sessions: dict[str, set[int]] = defaultdict(set)

    for s in sets:
        attribution = calc.attribute_set_to_muscles(
            s.primary_muscle, s.secondary_muscles, weighting=w
        )
        for muscle, share in attribution.items():
            if share >= w.primary:
                direct[muscle] += 1
            else:
                indirect[muscle] += share
            volume[muscle] += s.volume_kg * share
            sessions[muscle].add(s.workout_id)
            if muscle not in last_trained or s.day > last_trained[muscle]:
                last_trained[muscle] = s.day

    today = date.today()
    rows = []
    for muscle in sorted(set(direct) | set(indirect)):
        rows.append(
            {
                "muscle": muscle,
                "directSets": round(direct.get(muscle, 0.0), 1),
                "indirectSets": round(indirect.get(muscle, 0.0), 1),
                "volumeKg": round(volume.get(muscle, 0.0), 1),
                "sessions": len(sessions.get(muscle, ())),
                "lastTrained": last_trained[muscle].isoformat() if muscle in last_trained else None,
                "daysSince": (today - last_trained[muscle]).days if muscle in last_trained else None,
            }
        )
    return sorted(rows, key=lambda r: r["directSets"], reverse=True)


def detailed_muscle_volume(
    sets: list[SetRecord], *, weighting: calc.MuscleWeighting | None = None
) -> dict:
    """Per-muscle breakdown across the 27-muscle model, grouped by region.

    Reports the three tiers separately and a percentage share of the window's
    total attributed work. The share is what makes a session legible at a
    glance ("this was 45% chest") in a way raw set counts are not — but the
    tiers stay visible underneath, because a muscle whose share is all
    stabiliser work has not been trained in any meaningful sense.
    """
    w = weighting or calc.MuscleWeighting()
    tiers: dict[str, dict[str, float]] = {}
    volume: dict[str, float] = {}
    weighted: dict[str, float] = {}
    last_trained: dict[str, date] = {}
    sessions: dict[str, set[int]] = {}

    for s in sets:
        for muscle, (share, tier) in calc.attribute_set_detailed(
            s.muscle_attribution, weighting=w
        ).items():
            bucket = tiers.setdefault(
                muscle, {"primary": 0.0, "secondary": 0.0, "stabiliser": 0.0}
            )
            bucket[tier] += 1
            weighted[muscle] = weighted.get(muscle, 0.0) + share
            volume[muscle] = volume.get(muscle, 0.0) + s.volume_kg * share
            sessions.setdefault(muscle, set()).add(s.workout_id)
            if muscle not in last_trained or s.day > last_trained[muscle]:
                last_trained[muscle] = s.day

    total_weighted = sum(weighted.values()) or 1.0
    total_volume = sum(volume.values()) or 1.0
    today = date.today()

    rows = []
    for muscle, bucket in tiers.items():
        rows.append({
            "muscle": muscle,
            "region": muscles.region_for(muscle),
            "primarySets": round(bucket["primary"], 1),
            "secondarySets": round(bucket["secondary"], 1),
            "stabiliserSets": round(bucket["stabiliser"], 1),
            "weightedSets": round(weighted[muscle], 2),
            # Two shares, because they answer different questions and disagree
            # sharply. Set share is the programming currency ("sets per muscle
            # per week"); volume share follows the tonnage and is dominated by
            # whichever movement is heaviest. A session of heavy benching plus
            # light pushdowns is ~45% chest by volume and ~14% by sets — both
            # true, so neither is presented as *the* number.
            "sharePercent": round(weighted[muscle] / total_weighted * 100, 1),
            "volumeSharePercent": round(volume[muscle] / total_volume * 100, 1),
            "volumeKg": round(volume[muscle], 1),
            "sessions": len(sessions[muscle]),
            "lastTrained": last_trained[muscle].isoformat(),
            "daysSince": (today - last_trained[muscle]).days,
            # True when nothing but stabiliser work touched this muscle — it
            # appears in the chart but was not trained.
            "stabiliserOnly": bucket["primary"] == 0 and bucket["secondary"] == 0,
        })
    rows.sort(key=lambda r: r["weightedSets"], reverse=True)

    by_region: dict[str, float] = {}
    by_region_volume: dict[str, float] = {}
    for row in rows:
        by_region[row["region"]] = by_region.get(row["region"], 0.0) + row["weightedSets"]
        by_region_volume[row["region"]] = (
            by_region_volume.get(row["region"], 0.0) + row["volumeKg"]
        )
    regions = [
        {
            "region": region,
            "weightedSets": round(by_region[region], 2),
            "sharePercent": round(by_region[region] / total_weighted * 100, 1),
            "volumeKg": round(by_region_volume[region], 1),
            "volumeSharePercent": round(by_region_volume[region] / total_volume * 100, 1),
        }
        for region in muscles.REGION_ORDER
        if region in by_region
    ]
    regions.sort(key=lambda r: r["weightedSets"], reverse=True)

    untrained = [
        m for m in muscles.ALL_MUSCLES
        if m not in tiers or tiers[m]["primary"] + tiers[m]["secondary"] == 0
    ]

    return {
        "muscles": rows,
        "regions": regions,
        # Naming what got no direct work is often the more useful half: a
        # missing muscle has no row to notice.
        "untrained": untrained,
        "weighting": w.as_dict(),
        "note": (
            "Attribution is a mapping convention based on movement mechanics, "
            "not a measurement of your muscles."
        ),
    }


def balance_ratios(sets: list[SetRecord]) -> dict:
    """Push/pull, squat/hinge and upper/lower balance.

    Ratios are ``None`` when either side has no work at all. A push/pull ratio
    with zero pulling is not "infinity", it is a programme with no pulling in
    it, and the warning system says that in words instead.
    """
    by_pattern: dict[str, int] = defaultdict(int)
    for s in sets:
        by_pattern[s.movement_pattern] += 1

    push = by_pattern["horizontal_push"] + by_pattern["vertical_push"]
    pull = by_pattern["horizontal_pull"] + by_pattern["vertical_pull"]
    squat = by_pattern["squat"] + by_pattern["lunge"]
    hinge = by_pattern["hinge"]
    lower = squat + hinge + by_pattern["knee_extension"] + by_pattern["knee_flexion"] + by_pattern["calf"]
    upper = push + pull + by_pattern["elbow_flexion"] + by_pattern["elbow_extension"]

    def ratio(a: int, b: int) -> float | None:
        if a == 0 or b == 0:
            return None
        return round(a / b, 2)

    return {
        "pushSets": push, "pullSets": pull, "pushPull": ratio(push, pull),
        "squatSets": squat, "hingeSets": hinge, "squatHinge": ratio(squat, hinge),
        "upperSets": upper, "lowerSets": lower, "upperLower": ratio(upper, lower),
    }


# --------------------------------------------------------------------------- #
# Intensity
# --------------------------------------------------------------------------- #
def intensity_summary(sets: list[SetRecord]) -> dict:
    rated = [s for s in sets if s.rpe is not None]
    loads = [s.weight_kg for s in sets if s.weight_kg > 0]
    rep_buckets = {"1-5": 0, "6-8": 0, "9-12": 0, "13+": 0}
    for s in sets:
        if s.reps <= 5:
            rep_buckets["1-5"] += 1
        elif s.reps <= 8:
            rep_buckets["6-8"] += 1
        elif s.reps <= 12:
            rep_buckets["9-12"] += 1
        else:
            rep_buckets["13+"] += 1

    rpe_buckets: dict[str, int] = defaultdict(int)
    for s in rated:
        rpe_buckets[f"{s.rpe:g}"] += 1

    return {
        "averageLoadKg": round(statistics.fmean(loads), 1) if loads else None,
        "averageRpe": round(statistics.fmean([s.rpe for s in rated]), 2) if rated else None,
        "ratedShare": round(len(rated) / len(sets), 2) if sets else None,
        "repDistribution": rep_buckets,
        "rpeDistribution": dict(sorted(rpe_buckets.items())),
        "failureSets": sum(1 for s in sets if s.to_failure),
        "failureShare": round(sum(1 for s in sets if s.to_failure) / len(sets), 3) if sets else None,
    }


# --------------------------------------------------------------------------- #
# Strength trends
# --------------------------------------------------------------------------- #
def exercise_trend(sets: list[SetRecord], *, exercise_id: int) -> dict:
    """Per-session bests for one exercise, plus change over standard windows."""
    rows = [s for s in sets if s.exercise_id == exercise_id]
    by_session: dict[int, list[SetRecord]] = defaultdict(list)
    for s in rows:
        by_session[s.workout_id].append(s)

    points = []
    for workout_id, group in by_session.items():
        e1rms = [s.e1rm for s in group if s.e1rm]
        points.append(
            {
                "day": group[0].day.isoformat(),
                "workoutId": workout_id,
                "topSetKg": max(s.weight_kg for s in group),
                "bestE1rmKg": max(e1rms) if e1rms else None,
                "volumeKg": round(sum(s.volume_kg for s in group), 1),
                "sets": len(group),
                "totalReps": sum(s.reps for s in group),
            }
        )
    points.sort(key=lambda p: p["day"])

    return {
        "exerciseId": exercise_id,
        "name": rows[0].exercise_name if rows else "",
        "points": points,
        "changes": _window_changes(points),
        "plateau": detect_plateau(points),
    }


def _window_changes(points: list[dict]) -> list[dict]:
    """Change in best e1RM over 4, 8, 12 and 26 weeks.

    Reports the window as unavailable rather than comparing against whatever
    the oldest point happens to be — "up 40% over 26 weeks" is misleading when
    the history is three weeks long.
    """
    if not points:
        return []
    today = date.today()
    latest = next((p for p in reversed(points) if p["bestE1rmKg"]), None)
    out = []
    for weeks in (4, 8, 12, 26):
        cutoff = today - timedelta(weeks=weeks)
        earlier = [
            p for p in points
            if p["bestE1rmKg"] and date.fromisoformat(p["day"]) <= cutoff
        ]
        if not earlier or latest is None:
            out.append({"weeks": weeks, "available": False,
                        "reason": f"No data from {weeks} weeks ago to compare with."})
            continue
        base = earlier[-1]["bestE1rmKg"]
        delta = latest["bestE1rmKg"] - base
        out.append({
            "weeks": weeks, "available": True,
            "fromKg": base, "toKg": latest["bestE1rmKg"],
            "deltaKg": round(delta, 1),
            "percent": round(delta / base * 100, 1) if base else None,
        })
    return out


def detect_plateau(points: list[dict], *, min_sessions: int = MIN_PLATEAU_SESSIONS) -> dict:
    """Has this lift stopped moving?

    Requires ``min_sessions`` comparable exposures. Two unchanged sessions is a
    fortnight, not a plateau — and calling it one trains the operator to ignore
    the signal.
    """
    usable = [p for p in points if p["bestE1rmKg"]]
    if len(usable) < min_sessions:
        return {
            "plateaued": False,
            "confident": False,
            "reason": (
                f"{len(usable)} comparable session{'s' if len(usable) != 1 else ''} on record; "
                f"{min_sessions} needed before calling a plateau."
            ),
        }
    window = usable[-min_sessions:]
    values = [p["bestE1rmKg"] for p in window]
    best = max(values)
    latest = values[-1]
    spread = (best - min(values)) / best if best else 0.0
    improved = latest > values[0] * 1.01

    plateaued = not improved and spread < 0.03
    return {
        "plateaued": plateaued,
        "confident": True,
        "sessions": len(window),
        "spreadPercent": round(spread * 100, 1),
        "reason": (
            f"Best estimate has moved less than 3% across the last {len(window)} sessions."
            if plateaued
            else f"Best estimate is still moving across the last {len(window)} sessions."
        ),
    }


# --------------------------------------------------------------------------- #
# Adherence
# --------------------------------------------------------------------------- #
def adherence(user_id: int, *, since: date, until: date | None = None) -> dict:
    """Planned versus completed, kept strictly separate.

    A plan that was never started and a session that was started and abandoned
    are different events. Counting them together is the single easiest way to
    make an adherence figure that flatters and means nothing.
    """
    until = until or date.today()
    with session_scope() as s:
        planned = s.scalars(
            select(StrengthPlannedSession).where(
                StrengthPlannedSession.user_id == user_id,
                StrengthPlannedSession.planned_date >= since,
                StrengthPlannedSession.planned_date <= until,
            )
        ).all()
        workouts = s.scalars(
            select(StrengthWorkout).where(
                StrengthWorkout.user_id == user_id,
                StrengthWorkout.started_at >= datetime.combine(since, datetime.min.time()),
                StrengthWorkout.started_at <= datetime.combine(until, datetime.max.time()),
            )
        ).all()

        by_status: dict[str, int] = defaultdict(int)
        for p in planned:
            by_status[p.status] += 1
        rescheduled = sum(1 for p in planned if p.rescheduled_from is not None)

        completed = sum(1 for w in workouts if w.status == "completed")
        partial = sum(1 for w in workouts if w.status == "partial")
        abandoned = sum(1 for w in workouts if w.status == "abandoned")
        unplanned = sum(1 for w in workouts if w.planned_session_id is None
                        and w.status in COUNTED_STATUSES)

    planned_total = len(planned)
    done = completed + partial
    return {
        "from": since.isoformat(),
        "to": until.isoformat(),
        "plannedSessions": planned_total,
        "completedSessions": completed,
        "partialSessions": partial,
        "abandonedSessions": abandoned,
        "skippedSessions": by_status.get("skipped", 0),
        "rescheduledSessions": rescheduled,
        # Unplanned sessions are counted but kept out of the rate: training
        # that was never scheduled cannot be adherence to a schedule.
        "unplannedSessions": unplanned,
        "completionRate": round(done / planned_total, 2) if planned_total else None,
        "rateAvailable": planned_total > 0,
        "note": (
            "No sessions were scheduled in this window, so there is no plan to "
            "measure adherence against."
            if not planned_total else ""
        ),
    }


# --------------------------------------------------------------------------- #
# Readiness ↔ performance
# --------------------------------------------------------------------------- #
def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def readiness_associations(user_id: int, *, since: date | None = None) -> list[dict]:
    """Associations between pre-session state and what happened in the session.

    Deliberately cautious. Every row reports its sample size and date range,
    describes direction rather than cause, and anything under
    ``MIN_CORRELATION_N`` pairs is refused outright with the reason stated. A
    personal training log will not produce causal evidence, and presenting a
    coefficient over six sessions as insight would be the most dishonest thing
    in this whole module.
    """
    with session_scope() as s:
        workouts = s.scalars(
            select(StrengthWorkout)
            .where(
                StrengthWorkout.user_id == user_id,
                StrengthWorkout.status.in_(COUNTED_STATUSES),
            )
            .order_by(StrengthWorkout.started_at)
        ).all()
        rows = [
            {
                "id": w.id,
                "day": w.started_at.date(),
                "readiness": w.readiness_snapshot or {},
                "sessionRpe": w.session_rpe,
            }
            for w in workouts
            if since is None or w.started_at.date() >= since
        ]

    sets = _load_sets(user_id, since=since)
    volume_by_workout: dict[int, float] = defaultdict(float)
    for s_ in sets:
        volume_by_workout[s_.workout_id] += s_.volume_kg

    definitions = [
        ("sleepHours", "Sleep the night before", "session volume", "volume"),
        ("hrvMs", "HRV", "session volume", "volume"),
        ("restingHr", "Resting heart rate", "session RPE", "rpe"),
    ]

    out = []
    for key, label, outcome_label, outcome in definitions:
        pairs = []
        for row in rows:
            x = row["readiness"].get(key)
            y = volume_by_workout.get(row["id"]) if outcome == "volume" else row["sessionRpe"]
            if x is None or y is None:
                continue
            pairs.append((float(x), float(y)))

        if len(pairs) < MIN_CORRELATION_N:
            out.append({
                "input": label,
                "outcome": outcome_label,
                "available": False,
                "observations": len(pairs),
                "required": MIN_CORRELATION_N,
                "note": (
                    f"{len(pairs)} paired observation{'s' if len(pairs) != 1 else ''}. "
                    f"At least {MIN_CORRELATION_N} are needed before this is worth reporting."
                ),
            })
            continue

        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        r = _pearson(xs, ys)
        days = [row["day"] for row in rows]
        out.append({
            "input": label,
            "outcome": outcome_label,
            "available": True,
            "observations": len(pairs),
            "coefficient": round(r, 2) if r is not None else None,
            "direction": _direction(r),
            "strength": _strength_label(r),
            "from": min(days).isoformat() if days else None,
            "to": max(days).isoformat() if days else None,
            "missingRate": round(1 - len(pairs) / len(rows), 2) if rows else None,
            # The wording is the point: this is an association in one person's
            # log, not evidence of cause, and the copy must not imply otherwise.
            "note": (
                "An association in your own log, not evidence that one causes "
                "the other. Training, sleep and stress all move together."
            ),
        })
    return out


def _direction(r: float | None) -> str:
    if r is None:
        return "none"
    if r > 0.1:
        return "positive"
    if r < -0.1:
        return "negative"
    return "flat"


def _strength_label(r: float | None) -> str:
    if r is None:
        return "unknown"
    a = abs(r)
    if a >= 0.7:
        return "strong"
    if a >= 0.4:
        return "moderate"
    if a >= 0.2:
        return "weak"
    return "negligible"


# --------------------------------------------------------------------------- #
# Programme warnings
# --------------------------------------------------------------------------- #
def programme_warnings(sets: list[SetRecord]) -> list[dict]:
    """Advisory checks on what is actually being trained.

    Advisory, not absolute — every one of these has a legitimate reason to be
    true, so they are phrased as observations for the operator to overrule.
    """
    out: list[dict] = []
    if not sets:
        return out

    balance = balance_ratios(sets)
    if balance["pullSets"] == 0 and balance["pushSets"] > 0:
        out.append({
            "severity": "warning", "code": "no_pulling",
            "message": f"{balance['pushSets']} pushing sets and no pulling work in this window.",
        })
    elif balance["pushPull"] and balance["pushPull"] > 2.0:
        out.append({
            "severity": "info", "code": "push_pull_skew",
            "message": (f"Pushing outweighs pulling {balance['pushPull']:g}:1. "
                        "Common in upper-body work, worth knowing about."),
        })
    if balance["hingeSets"] == 0 and balance["squatSets"] > 0:
        out.append({
            "severity": "info", "code": "no_hinge",
            "message": "Squatting and lunging but no hinge work in this window.",
        })

    weekly = volume_by_period(sets, period="week")
    if len(weekly) >= 2:
        last, previous = weekly[-1], weekly[-2]
        if previous["volumeKg"] > 0:
            jump = last["volumeKg"] / previous["volumeKg"]
            if jump > 1.5:
                out.append({
                    "severity": "warning", "code": "volume_jump",
                    "message": (f"Volume rose {(jump - 1) * 100:.0f}% week on week "
                                f"({previous['volumeKg']:,.0f} → {last['volumeKg']:,.0f} kg)."),
                })

    unrated = sum(1 for s in sets if s.rpe is None and s.rir is None)
    if sets and unrated / len(sets) > 0.5:
        out.append({
            "severity": "info", "code": "mostly_unrated",
            "message": (f"{unrated} of {len(sets)} sets have no effort rating, so hard-set "
                        "counts and RPE-based progression are unavailable."),
        })
    return out


# --------------------------------------------------------------------------- #
# Top-level report
# --------------------------------------------------------------------------- #
def overview(user_id: int, *, days: int = 28) -> dict:
    """The Analytics screen's payload, computed once in one place."""
    since = date.today() - timedelta(days=days)
    sets = _load_sets(user_id, since=since)
    all_time = _load_sets(user_id)

    return {
        "windowDays": days,
        "from": since.isoformat(),
        "to": date.today().isoformat(),
        "summary": volume_summary(sets),
        "allTime": volume_summary(all_time),
        "byWeek": volume_by_period(sets, period="week"),
        "byExercise": volume_by_exercise(sets)[:12],
        "byMovement": volume_by_movement(sets),
        "byMuscle": muscle_volume(sets),
        "detailedMuscles": detailed_muscle_volume(sets),
        "balance": balance_ratios(sets),
        "intensity": intensity_summary(sets),
        "warnings": programme_warnings(sets),
        "adherence": adherence(user_id, since=since),
        "associations": readiness_associations(user_id),
        "weighting": calc.MuscleWeighting().as_dict(),
    }
