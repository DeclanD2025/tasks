"""Task review: turning a backlog into a triage list.

The homepage's job here is to replace one demoralising number with a few
actionable ones. "95 tasks past due" describes a person failing at everything.
The same data says: one publication's deadline wave slipped, four daily habits
rotted into permanent guilt, and two thirds of the list was never given a date.

Those are different problems with different fixes, and only the second framing
can be acted on.

Nothing here archives, deletes or reclassifies anything on its own. It sorts
into buckets and proposes; the operator decides. The habit inference in
particular is a guess from a title, and a wrong guess that acted alone would
silently delete a real task.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, timedelta

from app.domains.briefing.priorities import _project_of

#: Titles that look like recurring daily behaviour rather than one-off work.
#: Matched conservatively — these only ever produce a *suggestion* to convert
#: to a habit, never an automatic change.
_HABIT_PATTERNS = re.compile(
    r"\b(journal|duolingo|meditat|stretch|read|vitamin|water|steps|walk|"
    r"floss|skincare|practice|revision|language)\b",
    re.IGNORECASE,
)

#: Undisturbed for this long with a date already passed → likely abandoned.
_STALE_DAYS = 30


def review_buckets(tasks: list[dict], *, today: date | None = None) -> dict:
    """Sort the open backlog into things the operator can actually act on."""
    today = today or date.today()
    open_tasks = [
        t for t in tasks
        if t.get("status") != "done" and not t.get("archived_at")
    ]

    needs_date: list[dict] = []
    stale: list[dict] = []
    habit_candidates: list[dict] = []
    blocked: list[dict] = []
    overdue: list[dict] = []

    for task in open_tasks:
        if task.get("review_status") not in {"unreviewed", "", None}:
            continue  # already triaged
        due = task.get("due_date")

        if task.get("blocked"):
            blocked.append(task)
            continue
        if due and _HABIT_PATTERNS.search(task.get("title") or ""):
            habit_candidates.append(task)
            continue
        if due and due < today:
            if (today - due).days > _STALE_DAYS:
                stale.append(task)
            else:
                overdue.append(task)
            continue
        if due is None:
            needs_date.append(task)

    projects = _merge_related(Counter(_project_of(t.get("area")) for t in overdue))
    dominant = projects.most_common(1)[0] if projects else None

    return {
        "total": len(open_tasks),
        "buckets": [
            _bucket("overdue", "Past their date", overdue,
                    _overdue_framing(overdue, dominant)),
            _bucket("needs_date", "No date set", needs_date,
                    "Never scheduled, so they cannot come up on their own."),
            _bucket("habit_candidates", "Look like habits", habit_candidates,
                    "Daily behaviours carrying a one-off due date. They read as "
                    "failures every day instead of as a streak."),
            _bucket("stale", "Probably dead", stale,
                    f"More than {_STALE_DAYS} days past their date and untouched."),
            _bucket("blocked", "Waiting on something", blocked,
                    "Blocked on someone or something else."),
        ],
        # The reframing that does the real work on the homepage.
        "headline": _overdue_framing(overdue, dominant),
        "dominantProject": dominant[0] if dominant else None,
    }


def _merge_related(projects: Counter) -> Counter:
    """Fold a project into its parent when one name prefixes another.

    Production has both "Steelmen Dispatch" (37 items) and "Steelmen Dispatch
    Issue 4" (53). Counted separately, neither clears the threshold to be named
    — so the page said "spread across several areas" about a backlog that is 98%
    one publication. Merging on prefix is a narrow rule and a safe one: an area
    that starts with another area's full name is a sub-area of it.
    """
    if len(projects) < 2:
        return projects
    merged: Counter = Counter()
    names = sorted(projects, key=len)  # shortest first — parents before children
    for name in projects:
        parent = next(
            (p for p in names if p != name and _is_sub_project(name, p)),
            name,
        )
        merged[parent] += projects[name]
    return merged


def _is_sub_project(name: str, parent: str) -> bool:
    """Is ``name`` a sub-project of ``parent``?

    A bare `startswith` would fold "Homework" into "Home", which is a different
    area entirely. Requiring a word boundary after the parent name keeps the
    rule useful ("Steelmen Dispatch Issue 4" → "Steelmen Dispatch") without it
    merging things that merely share an opening substring.
    """
    if not name.startswith(parent):
        return False
    remainder = name[len(parent):]
    return remainder[:1] in {" ", "/", ":", "-", ""}


def _bucket(key: str, label: str, tasks: list[dict], note: str) -> dict:
    return {
        "key": key,
        "label": label,
        "count": len(tasks),
        "note": note if tasks else "",
        # A few examples only. The full workflow lives on the review screen —
        # the homepage is not the place to work through 95 items.
        "examples": [
            {
                "taskId": t["id"],
                "title": t["title"],
                "area": t.get("area") or "Unsorted",
                "dueDate": t["due_date"].isoformat() if t.get("due_date") else None,
            }
            for t in tasks[:3]
        ],
    }


def _overdue_framing(overdue: list[dict], dominant) -> str:
    """Say what the overdue pile actually is.

    With 90 of 95 items in one project, "95 tasks past due" is technically true
    and practically a lie about the operator's life.
    """
    if not overdue:
        return "Nothing past its date."
    total = len(overdue)
    if dominant is None:
        return f"{total} past their date."
    name, count = dominant
    if count / total >= 0.6:
        return (
            f"{count} of {total} items past their date belong to {name} — "
            "one project's schedule slipped, rather than everything at once."
        )
    return f"{total} items past their date, spread across several areas."


def mark_reviewed(uid: int, task_id: int, status: str, **fields) -> None:
    """Record a triage decision.

    Archiving keeps the row and its reason — an abandoned task still explains a
    gap in a project's history, and deleting it makes that gap unexplainable.
    """
    from datetime import datetime

    from sqlalchemy import select

    from app.db.database import session_scope
    from app.db.models import Task

    allowed = {
        "defer_until", "next_action", "estimate_minutes", "energy", "impact",
        "blocked", "waiting_for", "pinned_for", "archived_reason",
    }
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Cannot set: {', '.join(sorted(unknown))}")

    with session_scope() as s:
        task = s.scalars(
            select(Task).where(Task.id == task_id, Task.user_id == uid)
        ).first()
        if task is None:
            raise ValueError("That task does not exist.")
        task.review_status = status
        task.reviewed_at = datetime.utcnow()
        for key, value in fields.items():
            setattr(task, key, value)
        if status == "archived":
            task.archived_at = datetime.utcnow()
