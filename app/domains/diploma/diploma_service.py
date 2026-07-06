"""Diploma module service — a local, hand-editable study tracker.

Edited in-app, persisted to SQLite, no LLM. Study is tracked by *status and
preparedness*, not by hours logged: assignments carry a submission status and
exams carry a 0–100 readiness rating. The headline metrics are deterministic:

  * Weighted average grade across completed modules.
  * Progress to completion = credits earned / credits required.
  * Assessment load = upcoming assessments and how ready they are.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select

from app.db.database import session_scope
from app.db.models import DiplomaAssessment, DiplomaModule, DiplomaProgram

# Coursework submission states and exam states, in order.
ASSIGNMENT_STATES = ["not_started", "in_progress", "submitted", "graded"]
EXAM_STATES = ["revising", "ready"]
MODULE_STATES = ["ongoing", "done"]


@dataclass
class ModuleItem:
    id: int
    name: str
    credits: int
    weight: float
    grade: float | None
    status: str


@dataclass
class AssessmentItem:
    id: int
    title: str
    kind: str            # assignment | exam
    due_date: date | None
    status: str
    readiness: int
    module_id: int | None


@dataclass
class ProgramInfo:
    id: int
    name: str
    awarding_body: str
    credits_required: int
    target_date: date | None


@dataclass
class DiplomaSnapshot:
    program: ProgramInfo
    modules: list[ModuleItem]
    assessments: list[AssessmentItem]
    weighted_average: float | None   # None when no graded modules yet
    credits_earned: int
    progress_pct: float              # 0..100
    prepared_pct: float | None       # mean readiness of open assessments, or None
    open_assessment_count: int = field(default=0)


# --------------------------------------------------------------------------- #
# Program
# --------------------------------------------------------------------------- #
def get_or_create_program(user_id: int) -> ProgramInfo:
    with session_scope() as s:
        prog = s.scalars(
            select(DiplomaProgram).where(DiplomaProgram.user_id == user_id)
        ).first()
        if prog is None:
            prog = DiplomaProgram(user_id=user_id)
            s.add(prog)
            s.flush()
        return ProgramInfo(prog.id, prog.name, prog.awarding_body,
                           prog.credits_required, prog.target_date)


def update_program(
    user_id: int,
    *,
    name: str | None = None,
    awarding_body: str | None = None,
    credits_required: int | None = None,
    target_date: date | None = None,
) -> None:
    with session_scope() as s:
        prog = s.scalars(
            select(DiplomaProgram).where(DiplomaProgram.user_id == user_id)
        ).first()
        if prog is None:
            prog = DiplomaProgram(user_id=user_id)
            s.add(prog)
        if name is not None and name.strip():
            prog.name = name.strip()
        if awarding_body is not None:
            prog.awarding_body = awarding_body.strip()
        if credits_required is not None:
            prog.credits_required = max(1, credits_required)
        if target_date is not None:
            prog.target_date = target_date


# --------------------------------------------------------------------------- #
# Modules
# --------------------------------------------------------------------------- #
def list_modules(user_id: int) -> list[ModuleItem]:
    with session_scope() as s:
        rows = s.scalars(
            select(DiplomaModule).where(DiplomaModule.user_id == user_id)
            .order_by(DiplomaModule.sort_order, DiplomaModule.id)
        ).all()
        return [
            ModuleItem(r.id, r.name, r.credits, r.weight, r.grade, r.status)
            for r in rows
        ]


def add_module(user_id: int, name: str, credits: int = 15) -> int:
    with session_scope() as s:
        n = s.query(DiplomaModule).filter_by(user_id=user_id).count()
        row = DiplomaModule(user_id=user_id, name=name.strip() or "New module",
                            credits=credits, sort_order=n)
        s.add(row)
        s.flush()
        return row.id


def update_module(module_id: int, *, name: str | None = None, credits: int | None = None,
                  weight: float | None = None, grade: float | None = None,
                  status: str | None = None) -> None:
    with session_scope() as s:
        row = s.get(DiplomaModule, module_id)
        if row is None:
            return
        if name is not None and name.strip():
            row.name = name.strip()
        if credits is not None:
            row.credits = max(0, credits)
        if weight is not None:
            row.weight = max(0.0, weight)
        if grade is not None:
            row.grade = max(0.0, min(100.0, grade)) if grade >= 0 else None
        if status is not None and status in MODULE_STATES:
            row.status = status


def delete_module(module_id: int) -> None:
    _delete(DiplomaModule, module_id)


# --------------------------------------------------------------------------- #
# Assessments
# --------------------------------------------------------------------------- #
def list_assessments(user_id: int) -> list[AssessmentItem]:
    with session_scope() as s:
        rows = s.scalars(
            select(DiplomaAssessment).where(DiplomaAssessment.user_id == user_id)
            .order_by(DiplomaAssessment.due_date.is_(None),
                      DiplomaAssessment.due_date, DiplomaAssessment.id)
        ).all()
        return [
            AssessmentItem(r.id, r.title, r.kind, r.due_date, r.status,
                           r.readiness, r.module_id)
            for r in rows
        ]


def add_assessment(user_id: int, title: str, kind: str = "assignment",
                   due_date: date | None = None) -> int:
    status = "not_started" if kind == "assignment" else "revising"
    with session_scope() as s:
        n = s.query(DiplomaAssessment).filter_by(user_id=user_id).count()
        row = DiplomaAssessment(user_id=user_id, title=title.strip() or "New assessment",
                                kind=kind, due_date=due_date, status=status, sort_order=n)
        s.add(row)
        s.flush()
        return row.id


def update_assessment(assessment_id: int, *, status: str | None = None,
                      readiness: int | None = None,
                      due_date: date | None = None) -> None:
    with session_scope() as s:
        row = s.get(DiplomaAssessment, assessment_id)
        if row is None:
            return
        if status is not None:
            row.status = status
        if readiness is not None:
            row.readiness = max(0, min(100, readiness))
        if due_date is not None:
            row.due_date = due_date


def delete_assessment(assessment_id: int) -> None:
    _delete(DiplomaAssessment, assessment_id)


def _delete(model, row_id: int) -> None:
    with session_scope() as s:
        row = s.get(model, row_id)
        if row is not None:
            s.delete(row)


# --------------------------------------------------------------------------- #
# Snapshot + deterministic derivations
# --------------------------------------------------------------------------- #
def _weighted_average(modules: list[ModuleItem]) -> float | None:
    graded = [m for m in modules if m.grade is not None and m.status == "done"]
    if not graded:
        return None
    total_w = sum(m.weight * m.credits for m in graded) or 1.0
    blended = sum((m.grade or 0.0) * m.weight * m.credits for m in graded) / total_w
    return round(blended, 1)


def _open_unfinished(a: AssessmentItem) -> bool:
    if a.kind == "assignment":
        return a.status not in ("submitted", "graded")
    return a.status != "ready"


def get_snapshot(user_id: int) -> DiplomaSnapshot:
    program = get_or_create_program(user_id)
    modules = list_modules(user_id)
    assessments = list_assessments(user_id)

    credits_earned = sum(m.credits for m in modules if m.status == "done")
    progress_pct = round(
        min(100.0, credits_earned / max(1, program.credits_required) * 100.0), 1
    )

    open_assess = [a for a in assessments if _open_unfinished(a)]
    if open_assess:
        # Preparedness: exams use readiness; assignments map status → readiness.
        def _ready(a: AssessmentItem) -> float:
            if a.kind == "exam":
                return float(a.readiness)
            return {"not_started": 0.0, "in_progress": 50.0,
                    "submitted": 100.0, "graded": 100.0}.get(a.status, 0.0)
        prepared_pct = round(sum(_ready(a) for a in open_assess) / len(open_assess), 1)
    else:
        prepared_pct = None

    return DiplomaSnapshot(
        program=program,
        modules=modules,
        assessments=assessments,
        weighted_average=_weighted_average(modules),
        credits_earned=credits_earned,
        progress_pct=progress_pct,
        prepared_pct=prepared_pct,
        open_assessment_count=len(open_assess),
    )
