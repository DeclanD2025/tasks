"""The progression rules engine.

This is a **rules engine, not intelligence**, and the distinction is load
bearing. Every proposal states the rule that produced it, the inputs it looked
at, and the reason in plain words. Nothing is ever applied automatically: the
engine proposes, the operator decides, and both halves of that exchange are
recorded — including the rejections, which are the more informative half. A
rule the operator overrides every week is a rule that does not fit them, and
that is only visible if the misses are kept.

The core decision function is pure: last session's sets plus a config go in, a
``Proposal`` comes out. No database, no clock, no hidden state. Every rule is
therefore testable against a handful of literal sets, which is the only way to
have confidence in logic that will quietly shape years of training.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select

from app.db.database import session_scope
from app.db.models import StrengthExercise, StrengthProgressionEvent, utcnow
from app.domains.strength import calc


@dataclass(frozen=True)
class PerformedSet:
    """One working set as the engine sees it."""

    weight_kg: float
    reps: int
    rpe: float | None = None
    rir: float | None = None
    set_type: str = "working"
    to_failure: bool = False


@dataclass
class Proposal:
    """A suggested change, with everything needed to judge it."""

    rule: str
    action: str  # increase | hold | reduce | deload | none
    reason: str
    next_weight_kg: float | None = None
    next_reps: int | None = None
    next_rep_target: str = ""
    delta_kg: float | None = None
    inputs: dict = field(default_factory=dict)
    #: False when the rule could not reach a conclusion — no history, missing
    #: effort ratings. Distinct from "hold", which is a real decision.
    conclusive: bool = True

    def as_dict(self) -> dict:
        return {
            "rule": self.rule,
            "action": self.action,
            "reason": self.reason,
            "nextWeightKg": self.next_weight_kg,
            "nextReps": self.next_reps,
            "nextRepTarget": self.next_rep_target,
            "deltaKg": self.delta_kg,
            "inputs": self.inputs,
            "conclusive": self.conclusive,
        }


def _working(sets: list[PerformedSet]) -> list[PerformedSet]:
    return [s for s in sets if calc.is_working_set(s.set_type)]


def _inconclusive(rule: str, reason: str) -> Proposal:
    return Proposal(rule=rule, action="none", reason=reason, conclusive=False)


# --------------------------------------------------------------------------- #
# Rules
# --------------------------------------------------------------------------- #
def double_progression(
    sets: list[PerformedSet],
    *,
    rep_min: int,
    rep_max: int,
    increment_kg: float = 2.5,
    target_rpe: float | None = None,
    consecutive_misses: int = 0,
    miss_limit: int = 2,
) -> Proposal:
    """Work up the rep range at a fixed load, then add weight and drop back.

    The canonical example from the brief: 3×6–8, and when every working set
    reaches 8 at or under the target RPE, the load goes up next session.

    Two guards matter. Requiring *every* set to hit the top of the range stops
    one good first set from driving a load increase the later sets will not
    support. And when a target RPE is set, sets that hit the reps but blew past
    the RPE do not trigger an increase — hitting 8 reps at RPE 10 is not the
    same event as hitting 8 at RPE 8, and treating them alike is how a lifter
    ends up grinding.
    """
    working = _working(sets)
    if not working:
        return _inconclusive("double_progression", "No working sets recorded last session.")

    loads = {s.weight_kg for s in working}
    load = max(loads)
    reps = [s.reps for s in working]
    inputs = {
        "sets": [{"weightKg": s.weight_kg, "reps": s.reps, "rpe": s.rpe} for s in working],
        "repRange": [rep_min, rep_max],
        "targetRpe": target_rpe,
        "consecutiveMisses": consecutive_misses,
    }

    all_at_top = all(r >= rep_max for r in reps)
    rpe_ok = True
    if target_rpe is not None:
        rated = [s.rpe for s in working if s.rpe is not None]
        if not rated:
            # No ratings, so the RPE condition cannot be checked. Reps alone
            # are not enough to justify a load increase against an RPE cap.
            return Proposal(
                rule="double_progression",
                action="hold",
                reason=(
                    f"All sets reached {rep_max} reps, but no RPE was recorded, "
                    f"so the RPE {target_rpe:g} cap could not be checked."
                ),
                next_weight_kg=load,
                inputs=inputs,
                conclusive=all_at_top,
            ) if all_at_top else _inconclusive(
                "double_progression", "No RPE recorded, so the cap cannot be checked."
            )
        rpe_ok = max(rated) <= target_rpe

    if all_at_top and rpe_ok:
        new_load = calc.round_to_increment(load + increment_kg, increment_kg)
        return Proposal(
            rule="double_progression",
            action="increase",
            reason=(
                f"Every working set hit {rep_max} reps"
                + (f" at RPE {max(s.rpe for s in working if s.rpe is not None):g} or below"
                   if target_rpe is not None else "")
                + f". Add {increment_kg:g} kg and start again at {rep_min}."
            ),
            next_weight_kg=new_load,
            next_reps=rep_min,
            next_rep_target=f"{rep_min}–{rep_max}",
            delta_kg=new_load - load,
            inputs=inputs,
        )

    below_min = [r for r in reps if r < rep_min]
    if below_min and consecutive_misses + 1 >= miss_limit:
        new_load = calc.round_to_increment(load * 0.9, increment_kg)
        return Proposal(
            rule="double_progression",
            action="reduce",
            reason=(
                f"Missed the {rep_min}-rep minimum in {miss_limit} consecutive "
                f"sessions. Drop to {new_load:g} kg and build back up."
            ),
            next_weight_kg=new_load,
            next_reps=rep_min,
            next_rep_target=f"{rep_min}–{rep_max}",
            delta_kg=new_load - load,
            inputs=inputs,
        )

    return Proposal(
        rule="double_progression",
        action="hold",
        reason=(
            f"Reps were {'/'.join(str(r) for r in reps)} against a {rep_min}–{rep_max} "
            f"range. Stay at {load:g} kg until every set reaches {rep_max}."
        ),
        next_weight_kg=load,
        next_rep_target=f"{rep_min}–{rep_max}",
        inputs=inputs,
    )


def fixed_load(sets: list[PerformedSet], *, increment_kg: float = 2.5,
               target_reps: int, increase_every_session: bool = True) -> Proposal:
    """Linear progression: hit the target reps, add weight next time."""
    working = _working(sets)
    if not working:
        return _inconclusive("fixed_load", "No working sets recorded last session.")
    load = max(s.weight_kg for s in working)
    inputs = {"sets": [{"weightKg": s.weight_kg, "reps": s.reps} for s in working],
              "targetReps": target_reps}

    if all(s.reps >= target_reps for s in working) and increase_every_session:
        new_load = calc.round_to_increment(load + increment_kg, increment_kg)
        return Proposal(
            rule="fixed_load", action="increase",
            reason=f"All sets hit {target_reps} reps. Add {increment_kg:g} kg.",
            next_weight_kg=new_load, next_reps=target_reps,
            delta_kg=new_load - load, inputs=inputs,
        )
    return Proposal(
        rule="fixed_load", action="hold",
        reason=f"Not every set reached {target_reps} reps. Repeat {load:g} kg.",
        next_weight_kg=load, next_reps=target_reps, inputs=inputs,
    )


def rpe_based(
    sets: list[PerformedSet],
    *,
    target_rpe: float,
    increment_kg: float = 2.5,
    tolerance: float = 0.5,
) -> Proposal:
    """Steer the load toward a target RPE.

    Uses the *mean* RPE across working sets rather than the last one: fatigue
    means the final set almost always rates highest, so steering on it alone
    would ratchet the load down over time.
    """
    working = [s for s in _working(sets) if s.rpe is not None]
    if not working:
        return _inconclusive("rpe_target", "No RPE recorded, so there is nothing to steer on.")

    load = max(s.weight_kg for s in working)
    mean_rpe = sum(s.rpe for s in working) / len(working)
    inputs = {"meanRpe": round(mean_rpe, 2), "targetRpe": target_rpe,
              "sets": [{"weightKg": s.weight_kg, "reps": s.reps, "rpe": s.rpe} for s in working]}

    if mean_rpe < target_rpe - tolerance:
        new_load = calc.round_to_increment(load + increment_kg, increment_kg)
        return Proposal(
            rule="rpe_target", action="increase",
            reason=(f"Average RPE was {mean_rpe:.1f} against a target of {target_rpe:g} — "
                    f"there was more in the tank. Add {increment_kg:g} kg."),
            next_weight_kg=new_load, delta_kg=new_load - load, inputs=inputs,
        )
    if mean_rpe > target_rpe + tolerance:
        new_load = calc.round_to_increment(load - increment_kg, increment_kg)
        return Proposal(
            rule="rpe_target", action="reduce",
            reason=(f"Average RPE was {mean_rpe:.1f} against a target of {target_rpe:g} — "
                    f"harder than intended. Take {increment_kg:g} kg off."),
            next_weight_kg=new_load, delta_kg=new_load - load, inputs=inputs,
        )
    return Proposal(
        rule="rpe_target", action="hold",
        reason=f"Average RPE {mean_rpe:.1f} is on target. Repeat {load:g} kg.",
        next_weight_kg=load, inputs=inputs,
    )


def rir_based(sets: list[PerformedSet], *, target_rir: float, **kwargs) -> Proposal:
    """RIR is the same steering problem on the inverted scale."""
    converted = [
        PerformedSet(
            weight_kg=s.weight_kg, reps=s.reps,
            rpe=s.rpe if s.rpe is not None else calc.rir_to_rpe(s.rir),
            set_type=s.set_type, to_failure=s.to_failure,
        )
        for s in sets
    ]
    proposal = rpe_based(converted, target_rpe=calc.rir_to_rpe(target_rir), **kwargs)
    proposal.rule = "rir_target"
    proposal.inputs["targetRir"] = target_rir
    return proposal


def percentage_based(
    *, one_rm_kg: float, percent: float, reps: int, increment_kg: float = 2.5
) -> Proposal:
    """Prescribe from a percentage of a known or estimated 1RM."""
    raw = one_rm_kg * percent
    load = calc.round_to_increment(raw, increment_kg)
    return Proposal(
        rule="percentage", action="increase" if load else "none",
        reason=f"{percent:.0%} of a {one_rm_kg:g} kg max, rounded to the nearest {increment_kg:g} kg.",
        next_weight_kg=load, next_reps=reps,
        inputs={"oneRmKg": one_rm_kg, "percent": percent, "rawKg": round(raw, 2)},
    )


def amrap_triggered(
    sets: list[PerformedSet],
    *,
    amrap_target: int,
    increment_kg: float = 2.5,
    big_jump_threshold: int = 5,
    big_increment_kg: float | None = None,
) -> Proposal:
    """Size the next jump from how far past target the AMRAP set went.

    Beating the target by five or more reps earns a double increment: the load
    was clearly too light, and a single step would waste another session
    finding that out.
    """
    amraps = [s for s in sets if calc.normalise_set_type(s.set_type) == "amrap"]
    if not amraps:
        return _inconclusive("amrap_triggered", "No AMRAP set was recorded.")

    best = max(amraps, key=lambda s: s.reps)
    inputs = {"amrapReps": best.reps, "target": amrap_target, "weightKg": best.weight_kg}
    over = best.reps - amrap_target

    if over >= big_jump_threshold:
        step = big_increment_kg or increment_kg * 2
        new_load = calc.round_to_increment(best.weight_kg + step, increment_kg)
        return Proposal(
            rule="amrap_triggered", action="increase",
            reason=(f"AMRAP hit {best.reps} reps against a target of {amrap_target} — "
                    f"{over} over. Take a {step:g} kg jump."),
            next_weight_kg=new_load, delta_kg=new_load - best.weight_kg, inputs=inputs,
        )
    if over >= 0:
        new_load = calc.round_to_increment(best.weight_kg + increment_kg, increment_kg)
        return Proposal(
            rule="amrap_triggered", action="increase",
            reason=f"AMRAP met its {amrap_target}-rep target. Add {increment_kg:g} kg.",
            next_weight_kg=new_load, delta_kg=new_load - best.weight_kg, inputs=inputs,
        )
    return Proposal(
        rule="amrap_triggered", action="hold",
        reason=f"AMRAP reached {best.reps} of {amrap_target} reps. Repeat the load.",
        next_weight_kg=best.weight_kg, inputs=inputs,
    )


def deload(
    *, current_weight_kg: float, factor: float = 0.9, increment_kg: float = 2.5,
    reason: str = "Planned deload.",
) -> Proposal:
    new_load = calc.round_to_increment(current_weight_kg * factor, increment_kg)
    return Proposal(
        rule="deload", action="deload",
        reason=f"{reason} Drop to {factor:.0%} — {new_load:g} kg.",
        next_weight_kg=new_load, delta_kg=new_load - current_weight_kg,
        inputs={"currentKg": current_weight_kg, "factor": factor},
    )


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #
def propose(
    rule: str, sets: list[PerformedSet], *, config: dict | None = None,
    increment_kg: float = 2.5,
) -> Proposal:
    """Run whichever rule an exercise is configured for.

    An unknown rule returns an inconclusive proposal rather than raising: a
    typo in a programme should not stop a session from being logged.
    """
    cfg = dict(config or {})
    rule = (rule or "manual").lower()

    if rule == "manual":
        return Proposal(
            rule="manual", action="none",
            reason="This exercise progresses by hand.", conclusive=True,
        )
    if rule in ("double_progression", "rep_range"):
        return double_progression(
            sets,
            rep_min=int(cfg.get("repMin", 6)),
            rep_max=int(cfg.get("repMax", 8)),
            increment_kg=float(cfg.get("incrementKg", increment_kg)),
            target_rpe=cfg.get("targetRpe"),
            consecutive_misses=int(cfg.get("consecutiveMisses", 0)),
            miss_limit=int(cfg.get("missLimit", 2)),
        )
    if rule == "fixed_load":
        return fixed_load(
            sets, increment_kg=float(cfg.get("incrementKg", increment_kg)),
            target_reps=int(cfg.get("targetReps", 5)),
        )
    if rule == "rpe_target":
        return rpe_based(
            sets, target_rpe=float(cfg.get("targetRpe", 8)),
            increment_kg=float(cfg.get("incrementKg", increment_kg)),
        )
    if rule == "rir_target":
        return rir_based(
            sets, target_rir=float(cfg.get("targetRir", 2)),
            increment_kg=float(cfg.get("incrementKg", increment_kg)),
        )
    if rule == "percentage":
        one_rm = cfg.get("oneRmKg")
        if not one_rm:
            return _inconclusive("percentage", "No 1RM on file to take a percentage of.")
        return percentage_based(
            one_rm_kg=float(one_rm), percent=float(cfg.get("percent", 0.75)),
            reps=int(cfg.get("targetReps", 5)),
            increment_kg=float(cfg.get("incrementKg", increment_kg)),
        )
    if rule == "amrap_triggered":
        return amrap_triggered(
            sets, amrap_target=int(cfg.get("amrapTarget", 5)),
            increment_kg=float(cfg.get("incrementKg", increment_kg)),
        )
    if rule == "top_set_backoff":
        return top_set_backoff(
            sets, backoff_percent=float(cfg.get("backoffPercent", 0.85)),
            increment_kg=float(cfg.get("incrementKg", increment_kg)),
            target_reps=int(cfg.get("targetReps", 3)),
        )
    if rule == "deload":
        working = _working(sets)
        if not working:
            return _inconclusive("deload", "Nothing recorded to deload from.")
        return deload(
            current_weight_kg=max(s.weight_kg for s in working),
            factor=float(cfg.get("factor", 0.9)),
            increment_kg=float(cfg.get("incrementKg", increment_kg)),
        )
    return _inconclusive(rule, f"No rule named {rule!r} is implemented.")


def top_set_backoff(
    sets: list[PerformedSet], *, backoff_percent: float = 0.85,
    increment_kg: float = 2.5, target_reps: int = 3,
) -> Proposal:
    """Progress the heaviest set; derive the back-offs from it."""
    working = _working(sets)
    if not working:
        return _inconclusive("top_set_backoff", "No working sets recorded last session.")
    top = max(working, key=lambda s: s.weight_kg)
    inputs = {"topSetKg": top.weight_kg, "topSetReps": top.reps,
              "backoffPercent": backoff_percent}

    if top.reps >= target_reps:
        new_top = calc.round_to_increment(top.weight_kg + increment_kg, increment_kg)
        backoff = calc.round_to_increment(new_top * backoff_percent, increment_kg)
        return Proposal(
            rule="top_set_backoff", action="increase",
            reason=(f"Top set made {top.reps} reps at {top.weight_kg:g} kg. "
                    f"Go to {new_top:g} kg, back-offs at {backoff:g} kg."),
            next_weight_kg=new_top, next_reps=target_reps,
            delta_kg=new_top - top.weight_kg,
            inputs={**inputs, "backoffKg": backoff},
        )
    return Proposal(
        rule="top_set_backoff", action="hold",
        reason=f"Top set made {top.reps} of {target_reps} reps. Repeat {top.weight_kg:g} kg.",
        next_weight_kg=top.weight_kg, inputs=inputs,
    )


# --------------------------------------------------------------------------- #
# Recording decisions
# --------------------------------------------------------------------------- #
def record_proposal(
    user_id: int, exercise_id: int, proposal: Proposal, *,
    workout_id: int | None = None, programme_item_id: int | None = None,
) -> int:
    """Persist a proposal as pending. Returns the event id."""
    with session_scope() as s:
        event = StrengthProgressionEvent(
            user_id=user_id,
            exercise_id=exercise_id,
            workout_id=workout_id,
            programme_item_id=programme_item_id,
            rule=proposal.rule,
            inputs=proposal.inputs,
            proposal=proposal.as_dict(),
            reason=proposal.reason,
            decision="pending",
        )
        s.add(event)
        s.flush()
        return event.id


def decide(event_id: int, *, accepted: bool, applied: dict | None = None) -> None:
    """Record the operator's answer.

    Rejections are kept deliberately. A rule overridden every week is a rule
    that does not fit this lifter, and only the misses make that visible.
    """
    with session_scope() as s:
        event = s.get(StrengthProgressionEvent, event_id)
        if event is None:
            return
        event.decision = "accepted" if accepted else "rejected"
        event.decided_at = utcnow()
        if applied is not None:
            event.applied_prescription = applied


def pending_proposals(user_id: int) -> list[dict]:
    with session_scope() as s:
        rows = s.execute(
            select(StrengthProgressionEvent, StrengthExercise)
            .join(StrengthExercise, StrengthProgressionEvent.exercise_id == StrengthExercise.id)
            .where(
                StrengthProgressionEvent.user_id == user_id,
                StrengthProgressionEvent.decision == "pending",
            )
            .order_by(StrengthProgressionEvent.created_at.desc())
        ).all()
        return [
            {
                "id": event.id,
                "exercise": exercise.display_name or exercise.name,
                "exerciseId": exercise.id,
                "rule": event.rule,
                "reason": event.reason,
                "proposal": event.proposal,
                "inputs": event.inputs,
                "createdAt": event.created_at.isoformat(),
            }
            for event, exercise in rows
        ]
