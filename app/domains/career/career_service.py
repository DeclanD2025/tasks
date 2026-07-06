"""Career module service — a local, hand-editable career observatory.

Everything is edited in-app and persisted to SQLite. No external integration,
no LLM: the two headline matrices (Job Jeopardy and Economic Resilience) are
deterministic weighted blends of editable 0–100 factor scores. Each score
carries the factors that produced it so the UI can show the derivation.

Job Jeopardy   — higher = MORE at-risk (bad). Blends signals that raise risk.
Economic Resilience — higher = MORE resilient (good). Blends buffers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select

from app.db.database import session_scope
from app.db.models import (
    CareerGoal,
    CareerNote,
    CareerOpportunity,
    CareerPlanStep,
    CareerProfile,
    CareerSkill,
    TraineeshipApplication,
)

# Pipeline stages for opportunities, in order. Each maps to a 0–1 progress band.
PIPELINE_STAGES: list[str] = ["lead", "applied", "interview", "offer", "closed"]
PLAN_HORIZONS: list[str] = ["now", "next", "later"]
PLAN_STATUSES: list[str] = ["planned", "active", "blocked", "done"]
TRAINEESHIP_STATUSES: list[str] = [
    "researching",
    "preparing",
    "applied",
    "assessment",
    "interview",
    "offer",
    "rejected",
    "closed",
]

# --- Matrix definitions ----------------------------------------------------- #
# Each factor: (key, label, weight, higher_is_worse). For jeopardy, a high
# factor score means more risk; for resilience, a high score means more buffer.
JEOPARDY_FACTORS: list[tuple[str, str, float]] = [
    ("role_security", "Role security", 0.22),
    ("industry_health", "Industry health", 0.18),
    ("automation_exposure", "Automation exposure", 0.16),
    ("performance_standing", "Performance standing", 0.16),
    ("relationship_capital", "Relationship capital", 0.14),
    ("market_demand", "Skill market demand", 0.14),
]
# For jeopardy these are *protective* factors — a high score lowers risk — so
# jeopardy = 100 - weighted(protective). automation_exposure is the exception:
# a high score RAISES risk, so we invert it before blending.
JEOPARDY_INVERTED = {"automation_exposure"}

RESILIENCE_FACTORS: list[tuple[str, str, float]] = [
    ("emergency_runway", "Emergency runway", 0.26),
    ("income_diversity", "Income diversity", 0.20),
    ("low_fixed_costs", "Low fixed costs", 0.16),
    ("liquid_savings", "Liquid savings", 0.16),
    ("employability", "Employability", 0.12),
    ("debt_load", "Low debt load", 0.10),
]

_DEFAULT_FACTOR = 50  # neutral starting point for any unset factor


@dataclass
class MatrixFactor:
    key: str
    label: str
    weight: float
    score: int  # 0..100 as stored/edited


@dataclass
class MatrixScore:
    title: str
    code: str
    value: float           # 0..100 headline
    band: str              # qualitative band label
    higher_is_good: bool
    factors: list[MatrixFactor] = field(default_factory=list)


@dataclass
class GoalItem:
    id: int
    title: str
    target_date: date | None
    progress: int
    status: str


@dataclass
class SkillItem:
    id: int
    name: str
    proficiency: int
    momentum: str


@dataclass
class OpportunityItem:
    id: int
    role: str
    company: str
    stage: str


@dataclass
class NoteItem:
    id: int
    title: str
    body: str
    tag: str
    updated_on: date


@dataclass
class PlanStepItem:
    id: int
    title: str
    horizon: str
    status: str
    progress: int
    target_date: date | None
    notes: str


@dataclass
class TraineeshipItem:
    id: int
    programme: str
    provider: str
    status: str
    deadline: date | None
    contact: str
    progress: int
    notes: str


@dataclass
class ProfileInfo:
    id: int
    role_title: str
    employer: str
    started_on: date | None
    satisfaction: int
    notes: str


@dataclass
class CareerSnapshot:
    profile: ProfileInfo
    goals: list[GoalItem]
    skills: list[SkillItem]
    opportunities: list[OpportunityItem]
    notes: list[NoteItem]
    plan_steps: list[PlanStepItem]
    traineeships: list[TraineeshipItem]
    jeopardy: MatrixScore
    resilience: MatrixScore


# --------------------------------------------------------------------------- #
# Profile + matrices
# --------------------------------------------------------------------------- #
def get_or_create_profile(user_id: int) -> CareerProfile:
    with session_scope() as s:
        prof = s.scalars(
            select(CareerProfile).where(CareerProfile.user_id == user_id)
        ).first()
        if prof is None:
            prof = CareerProfile(user_id=user_id)
            s.add(prof)
            s.flush()
        s.expunge(prof)
        return prof


def update_profile(
    user_id: int,
    *,
    role_title: str | None = None,
    employer: str | None = None,
    started_on: date | None = None,
    satisfaction: int | None = None,
    notes: str | None = None,
) -> None:
    with session_scope() as s:
        prof = s.scalars(
            select(CareerProfile).where(CareerProfile.user_id == user_id)
        ).first()
        if prof is None:
            prof = CareerProfile(user_id=user_id)
            s.add(prof)
        if role_title is not None:
            prof.role_title = role_title.strip()
        if employer is not None:
            prof.employer = employer.strip()
        if started_on is not None:
            prof.started_on = started_on
        if satisfaction is not None:
            prof.satisfaction = max(0, min(100, satisfaction))
        if notes is not None:
            prof.notes = notes


def set_matrix_factor(user_id: int, matrix: str, key: str, score: int) -> None:
    """Persist a single factor score (0..100) for 'jeopardy' or 'resilience'."""
    score = max(0, min(100, int(score)))
    with session_scope() as s:
        prof = s.scalars(
            select(CareerProfile).where(CareerProfile.user_id == user_id)
        ).first()
        if prof is None:
            prof = CareerProfile(user_id=user_id)
            s.add(prof)
            s.flush()
        store = dict(prof.jeopardy if matrix == "jeopardy" else prof.resilience)
        store[key] = score
        if matrix == "jeopardy":
            prof.jeopardy = store
        else:
            prof.resilience = store


def _build_matrix(
    title: str,
    code: str,
    defs: list[tuple[str, str, float]],
    stored: dict,
    *,
    higher_is_good: bool,
    inverted: set[str] | None = None,
) -> MatrixScore:
    inverted = inverted or set()
    factors: list[MatrixFactor] = []
    blended = 0.0
    for key, label, weight in defs:
        raw = int(stored.get(key, _DEFAULT_FACTOR))
        factors.append(MatrixFactor(key, label, weight, raw))
        contribution = (100 - raw) if key in inverted else raw
        blended += contribution * weight

    if higher_is_good:
        value = blended
    else:
        # Jeopardy: protective factors blended high => low risk.
        value = 100.0 - blended
    value = round(max(0.0, min(100.0, value)), 1)
    return MatrixScore(title, code, value, _band(value, higher_is_good),
                       higher_is_good, factors)


def _band(value: float, higher_is_good: bool) -> str:
    if higher_is_good:
        if value >= 75:
            return "STRONG"
        if value >= 50:
            return "MODERATE"
        if value >= 30:
            return "FRAGILE"
        return "EXPOSED"
    # higher = worse (jeopardy)
    if value >= 70:
        return "HIGH RISK"
    if value >= 45:
        return "ELEVATED"
    if value >= 25:
        return "GUARDED"
    return "SECURE"


# --------------------------------------------------------------------------- #
# Goals / skills / opportunities (CRUD-lite)
# --------------------------------------------------------------------------- #
def list_goals(user_id: int) -> list[GoalItem]:
    with session_scope() as s:
        rows = s.scalars(
            select(CareerGoal).where(CareerGoal.user_id == user_id)
            .order_by(CareerGoal.sort_order, CareerGoal.id)
        ).all()
        return [GoalItem(r.id, r.title, r.target_date, r.progress, r.status) for r in rows]


def add_goal(user_id: int, title: str, target_date: date | None = None) -> int:
    with session_scope() as s:
        n = s.query(CareerGoal).filter_by(user_id=user_id).count()
        row = CareerGoal(user_id=user_id, title=title.strip() or "New goal",
                         target_date=target_date, sort_order=n)
        s.add(row)
        s.flush()
        return row.id


def update_goal(goal_id: int, *, progress: int | None = None,
                status: str | None = None, title: str | None = None) -> None:
    with session_scope() as s:
        row = s.get(CareerGoal, goal_id)
        if row is None:
            return
        if progress is not None:
            row.progress = max(0, min(100, progress))
        if status is not None:
            row.status = status
        if title is not None and title.strip():
            row.title = title.strip()


def delete_goal(goal_id: int) -> None:
    _delete(CareerGoal, goal_id)


def list_skills(user_id: int) -> list[SkillItem]:
    with session_scope() as s:
        rows = s.scalars(
            select(CareerSkill).where(CareerSkill.user_id == user_id)
            .order_by(CareerSkill.sort_order, CareerSkill.id)
        ).all()
        return [SkillItem(r.id, r.name, r.proficiency, r.momentum) for r in rows]


def add_skill(user_id: int, name: str) -> int:
    with session_scope() as s:
        n = s.query(CareerSkill).filter_by(user_id=user_id).count()
        row = CareerSkill(user_id=user_id, name=name.strip() or "New skill", sort_order=n)
        s.add(row)
        s.flush()
        return row.id


def update_skill(skill_id: int, *, proficiency: int | None = None,
                 momentum: str | None = None) -> None:
    with session_scope() as s:
        row = s.get(CareerSkill, skill_id)
        if row is None:
            return
        if proficiency is not None:
            row.proficiency = max(0, min(100, proficiency))
        if momentum is not None:
            row.momentum = momentum


def delete_skill(skill_id: int) -> None:
    _delete(CareerSkill, skill_id)


def list_opportunities(user_id: int) -> list[OpportunityItem]:
    with session_scope() as s:
        rows = s.scalars(
            select(CareerOpportunity).where(CareerOpportunity.user_id == user_id)
            .order_by(CareerOpportunity.sort_order, CareerOpportunity.id)
        ).all()
        return [OpportunityItem(r.id, r.role, r.company, r.stage) for r in rows]


def add_opportunity(user_id: int, role: str, company: str = "") -> int:
    with session_scope() as s:
        n = s.query(CareerOpportunity).filter_by(user_id=user_id).count()
        row = CareerOpportunity(user_id=user_id, role=role.strip() or "New role",
                                company=company.strip(), sort_order=n)
        s.add(row)
        s.flush()
        return row.id


def update_opportunity(opp_id: int, *, stage: str | None = None) -> None:
    with session_scope() as s:
        row = s.get(CareerOpportunity, opp_id)
        if row is None:
            return
        if stage is not None and stage in PIPELINE_STAGES:
            row.stage = stage


def delete_opportunity(opp_id: int) -> None:
    _delete(CareerOpportunity, opp_id)


def list_notes(user_id: int, limit: int = 6) -> list[NoteItem]:
    with session_scope() as s:
        rows = s.scalars(
            select(CareerNote).where(CareerNote.user_id == user_id)
            .order_by(CareerNote.updated_at.desc(), CareerNote.id.desc())
            .limit(limit)
        ).all()
        return [
            NoteItem(r.id, r.title, r.body, r.tag, r.updated_at.date())
            for r in rows
        ]


def add_note(user_id: int, title: str, body: str = "", tag: str = "reflection") -> int:
    with session_scope() as s:
        row = CareerNote(
            user_id=user_id,
            title=title.strip() or "Career note",
            body=body.strip(),
            tag=tag.strip() or "reflection",
        )
        s.add(row)
        s.flush()
        return row.id


def update_note(
    note_id: int,
    *,
    title: str | None = None,
    body: str | None = None,
    tag: str | None = None,
) -> None:
    with session_scope() as s:
        row = s.get(CareerNote, note_id)
        if row is None:
            return
        if title is not None and title.strip():
            row.title = title.strip()
        if body is not None:
            row.body = body.strip()
        if tag is not None and tag.strip():
            row.tag = tag.strip()


def delete_note(note_id: int) -> None:
    _delete(CareerNote, note_id)


def list_plan_steps(user_id: int) -> list[PlanStepItem]:
    with session_scope() as s:
        rows = s.scalars(
            select(CareerPlanStep).where(CareerPlanStep.user_id == user_id)
            .order_by(CareerPlanStep.sort_order, CareerPlanStep.id)
        ).all()
        return [
            PlanStepItem(
                r.id,
                r.title,
                r.horizon,
                r.status,
                r.progress,
                r.target_date,
                r.notes,
            )
            for r in rows
        ]


def add_plan_step(
    user_id: int,
    title: str,
    *,
    horizon: str = "next",
    target_date: date | None = None,
) -> int:
    with session_scope() as s:
        n = s.query(CareerPlanStep).filter_by(user_id=user_id).count()
        row = CareerPlanStep(
            user_id=user_id,
            title=title.strip() or "New career move",
            horizon=horizon if horizon in PLAN_HORIZONS else "next",
            target_date=target_date,
            sort_order=n,
        )
        s.add(row)
        s.flush()
        return row.id


def update_plan_step(
    step_id: int,
    *,
    title: str | None = None,
    horizon: str | None = None,
    status: str | None = None,
    progress: int | None = None,
    target_date: date | None = None,
    notes: str | None = None,
) -> None:
    with session_scope() as s:
        row = s.get(CareerPlanStep, step_id)
        if row is None:
            return
        if title is not None and title.strip():
            row.title = title.strip()
        if horizon is not None and horizon in PLAN_HORIZONS:
            row.horizon = horizon
        if status is not None and status in PLAN_STATUSES:
            row.status = status
        if progress is not None:
            row.progress = max(0, min(100, int(progress)))
        if target_date is not None:
            row.target_date = target_date
        if notes is not None:
            row.notes = notes.strip()


def delete_plan_step(step_id: int) -> None:
    _delete(CareerPlanStep, step_id)


def list_traineeships(user_id: int) -> list[TraineeshipItem]:
    with session_scope() as s:
        rows = s.scalars(
            select(TraineeshipApplication).where(TraineeshipApplication.user_id == user_id)
            .order_by(TraineeshipApplication.sort_order, TraineeshipApplication.id)
        ).all()
        return [
            TraineeshipItem(
                r.id,
                r.programme,
                r.provider,
                r.status,
                r.deadline,
                r.contact,
                r.progress,
                r.notes,
            )
            for r in rows
        ]


def add_traineeship(
    user_id: int,
    programme: str,
    provider: str = "",
    *,
    deadline: date | None = None,
) -> int:
    with session_scope() as s:
        n = s.query(TraineeshipApplication).filter_by(user_id=user_id).count()
        row = TraineeshipApplication(
            user_id=user_id,
            programme=programme.strip() or "New traineeship",
            provider=provider.strip(),
            deadline=deadline,
            sort_order=n,
        )
        s.add(row)
        s.flush()
        return row.id


def update_traineeship(
    traineeship_id: int,
    *,
    programme: str | None = None,
    provider: str | None = None,
    status: str | None = None,
    deadline: date | None = None,
    contact: str | None = None,
    progress: int | None = None,
    notes: str | None = None,
) -> None:
    with session_scope() as s:
        row = s.get(TraineeshipApplication, traineeship_id)
        if row is None:
            return
        if programme is not None and programme.strip():
            row.programme = programme.strip()
        if provider is not None:
            row.provider = provider.strip()
        if status is not None and status in TRAINEESHIP_STATUSES:
            row.status = status
        if deadline is not None:
            row.deadline = deadline
        if contact is not None:
            row.contact = contact.strip()
        if progress is not None:
            row.progress = max(0, min(100, int(progress)))
        if notes is not None:
            row.notes = notes.strip()


def delete_traineeship(traineeship_id: int) -> None:
    _delete(TraineeshipApplication, traineeship_id)


def _delete(model, row_id: int) -> None:
    with session_scope() as s:
        row = s.get(model, row_id)
        if row is not None:
            s.delete(row)


# --------------------------------------------------------------------------- #
# Snapshot
# --------------------------------------------------------------------------- #
def get_snapshot(user_id: int) -> CareerSnapshot:
    prof = get_or_create_profile(user_id)
    jeopardy = _build_matrix(
        "Job Jeopardy", "CAR-JPD", JEOPARDY_FACTORS, prof.jeopardy or {},
        higher_is_good=False, inverted=JEOPARDY_INVERTED,
    )
    resilience = _build_matrix(
        "Economic Resilience", "CAR-RES", RESILIENCE_FACTORS, prof.resilience or {},
        higher_is_good=True,
    )
    return CareerSnapshot(
        profile=ProfileInfo(prof.id, prof.role_title, prof.employer,
                            prof.started_on, prof.satisfaction, prof.notes),
        goals=list_goals(user_id),
        skills=list_skills(user_id),
        opportunities=list_opportunities(user_id),
        notes=list_notes(user_id),
        plan_steps=list_plan_steps(user_id),
        traineeships=list_traineeships(user_id),
        jeopardy=jeopardy,
        resilience=resilience,
    )
