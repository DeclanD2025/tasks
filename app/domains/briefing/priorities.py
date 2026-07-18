"""Transparent priority scoring.

Designed around a specific, awkward fact about this backlog: **the priority
field is useless.** 273 of 288 open tasks are "medium". Any ranking that leans
on it is ranking at random, so every signal here is derived from something
else — deadlines, project concentration, whether a next action exists, how
often a task has already been passed over.

Three rules the scorer obeys:

**No mystery number.** Every score is a sum of named components, each with its
own value and a sentence explaining it. The UI shows those, not the total. A
score the operator cannot interrogate is a score they cannot correct.

**Manual always wins.** A pinned task outranks everything the scorer produces,
without needing to beat it on points.

**Age is capped.** Left uncapped, the oldest task wins forever — and an old
task is usually old because it deserves to be, not because it is urgent.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date

#: Bump whenever the scoring, the selection or the brief's wording changes.
#: A stored brief carrying a different version is regenerated on next read —
#: see brief.generate. Without the bump, a deploy is invisible until tomorrow.
RULE_VERSION = "2"

#: Above this many days overdue, deadline pressure stops increasing. A task
#: three weeks late and one three months late are the same kind of problem, and
#: letting the gap grow without limit lets ancient items crowd out live ones.
_OVERDUE_CAP_DAYS = 21
#: Age contributes at most this. Deliberately small — see module docstring.
_MAX_AGE_POINTS = 8.0


@dataclass
class Component:
    """One named contribution to a score."""

    key: str
    label: str
    points: float
    detail: str

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "points": round(self.points, 1),
            "detail": self.detail,
        }


@dataclass
class ScoredTask:
    task: dict
    score: float
    components: list[Component] = field(default_factory=list)
    #: True when the operator pinned it — bypasses scoring entirely.
    pinned: bool = False
    excluded: str = ""

    def as_dict(self) -> dict:
        return {
            "taskId": self.task["id"],
            "title": self.task["title"],
            "area": self.task.get("area") or "Unsorted",
            "project": _project_of(self.task.get("area")),
            "dueDate": self.task["due_date"].isoformat() if self.task.get("due_date") else None,
            "nextAction": self.task.get("next_action") or "",
            "estimateMinutes": self.task.get("estimate_minutes"),
            "blocked": bool(self.task.get("blocked")),
            "waitingFor": self.task.get("waiting_for") or "",
            "score": round(self.score, 1),
            "components": [c.as_dict() for c in self.components],
            "why": self.headline_reason(),
            # Lets the UI drop a reason it is already showing. "19 days past its
            # date" beside a row that reads "19 days past" is the same fact
            # twice; the key makes that detectable without matching on prose.
            "whyKey": self.headline_key(),
            "selectedBy": "you" if self.pinned else "orion",
            "pinned": self.pinned,
        }

    def headline_reason(self) -> str:
        """The single most load-bearing reason, for the card.

        Picks the largest positive component rather than concatenating all of
        them: a card that lists six reasons has explained nothing.
        """
        component = self._headline_component()
        if component is None:
            return "No strong signal — surfaced because little else is scheduled."
        return component.detail

    def headline_key(self) -> str:
        """The key of the reason `headline_reason` describes, or "" if none."""
        component = self._headline_component()
        return component.key if component else ""

    def _headline_component(self) -> Component | None:
        positives = [c for c in self.components if c.points > 0]
        if not positives:
            return None
        return max(positives, key=lambda c: c.points)


def _project_of(area: str | None) -> str:
    """Top-level project from a slash-delimited area.

    "Steelmen Dispatch Issue 4 / Marketing" → "Steelmen Dispatch Issue 4".
    There is no project table; the area prefix is the only grouping available,
    and 198 of 288 tasks share one. Without this the homepage cannot say "one
    project's deadlines slipped" instead of "95 things are broken".
    """
    if not area:
        return "Unsorted"
    return area.split("/")[0].strip() or "Unsorted"


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
def score_task(
    task: dict,
    *,
    today: date,
    project_counts: Counter | None = None,
    minutes_available: int | None = None,
    energy: str = "",
) -> ScoredTask:
    """Score one task, returning every component that contributed."""
    components: list[Component] = []
    project_counts = project_counts or Counter()

    pinned = task.get("pinned_for") == today
    if pinned:
        return ScoredTask(
            task=task, score=1000.0, pinned=True,
            components=[Component("pinned", "You pinned this", 1000.0,
                                  "You chose this for today.")],
        )

    # --- exclusions -------------------------------------------------------- #
    if task.get("archived_at"):
        return ScoredTask(task, 0.0, excluded="archived")
    defer = task.get("defer_until")
    if defer and defer > today:
        return ScoredTask(task, 0.0, excluded=f"deferred until {defer.isoformat()}")
    if task.get("review_status") in {"stale", "convert_to_habit"}:
        return ScoredTask(task, 0.0, excluded="flagged in review")

    due = task.get("due_date")

    # --- deadline ---------------------------------------------------------- #
    if due == today:
        components.append(Component("due_today", "Due today", 40.0, "Due today."))
    elif due and due < today:
        days_late = min((today - due).days, _OVERDUE_CAP_DAYS)
        # Square-rooted and capped: the first days late matter most, and past
        # three weeks nothing is gained by ranking staleness against staleness.
        points = 12.0 + (days_late ** 0.5) * 4.0
        components.append(Component(
            "overdue", "Past its date", points,
            f"{(today - due).days} days past its date.",
        ))
    elif due:
        days_out = (due - today).days
        if days_out <= 7:
            points = max(0.0, 22.0 - days_out * 3.0)
            components.append(Component(
                "due_soon", "Due soon", points,
                f"Due in {days_out} day{'s' if days_out != 1 else ''}.",
            ))
    else:
        # 193 of 288 tasks are undated. Undated is not urgent, but it must not
        # be invisible either, or two thirds of the backlog can never surface.
        components.append(Component("undated", "No date", 2.0, "No date set."))

    # --- explicit priority, used lightly ----------------------------------- #
    # Worth 12 points at most, because "high" is 12 of 288 tasks and therefore
    # meaningful when present — but "medium" says nothing at all.
    if task.get("priority") == "high":
        components.append(Component("priority_high", "Marked high", 12.0,
                                    "You marked this high priority."))
    elif task.get("priority") == "low":
        components.append(Component("priority_low", "Marked low", -6.0,
                                    "You marked this low priority."))

    # --- readiness to act -------------------------------------------------- #
    if task.get("next_action"):
        components.append(Component("has_next_action", "Ready to start", 8.0,
                                    "The next step is already written down."))
    if task.get("blocked"):
        waiting = task.get("waiting_for") or "something else"
        components.append(Component("blocked", "Blocked", -30.0,
                                    f"Blocked, waiting on {waiting}."))

    # --- impact ------------------------------------------------------------ #
    impact = task.get("impact")
    if impact == "high":
        components.append(Component("impact", "High impact", 10.0, "You rated this high impact."))
    elif impact == "low":
        components.append(Component("impact", "Low impact", -4.0, "You rated this low impact."))

    # --- project concentration --------------------------------------------- #
    # A project with a wall of open work is where progress actually moves the
    # needle. This is what turns "95 unrelated failures" into "one deadline
    # wave worth an hour".
    project = _project_of(task.get("area"))
    open_in_project = project_counts.get(project, 0)
    if open_in_project >= 10:
        components.append(Component(
            "project_load", "Busiest project", 6.0,
            f"{open_in_project} open items in {project}.",
        ))

    # --- fit --------------------------------------------------------------- #
    estimate = task.get("estimate_minutes")
    if estimate and minutes_available:
        if estimate <= minutes_available:
            components.append(Component(
                "fits", "Fits the time you have", 6.0,
                f"About {estimate} min, and you have {minutes_available}.",
            ))
        else:
            components.append(Component(
                "too_long", "Longer than the time left", -8.0,
                f"Needs about {estimate} min; only {minutes_available} left.",
            ))
    if energy and task.get("energy"):
        if task["energy"] == energy:
            components.append(Component("energy_fit", "Matches your energy", 4.0,
                                        f"Suits {energy} energy."))
        elif energy == "low" and task["energy"] == "high":
            components.append(Component("energy_mismatch", "Demanding", -6.0,
                                        "Needs more energy than you have right now."))

    # --- age, capped ------------------------------------------------------- #
    created = task.get("remote_created_at") or task.get("created_at")
    if created is not None:
        created_day = created.date() if hasattr(created, "date") else created
        age_days = (today - created_day).days
        if age_days > 7:
            points = min(_MAX_AGE_POINTS, (age_days / 30.0) * 4.0)
            components.append(Component(
                "age", "Been waiting", points,
                f"Sitting for {age_days} days.",
            ))

    # --- repeated deferral -------------------------------------------------- #
    deferrals = int(task.get("deferral_count") or 0)
    if deferrals:
        # Passed over repeatedly means the task is wrong, not the day. Pushing
        # it down makes room and makes the pattern visible in review.
        components.append(Component(
            "deferred_before", "Passed over before", -5.0 * min(deferrals, 4),
            f"Offered and skipped {deferrals} time{'s' if deferrals != 1 else ''}.",
        ))

    total = sum(c.points for c in components)
    return ScoredTask(task=task, score=total, components=components)


def select_priorities(
    tasks: list[dict],
    *,
    today: date,
    limit: int = 3,
    minutes_available: int | None = None,
    energy: str = "",
) -> list[ScoredTask]:
    """Choose the day's priorities.

    Pinned tasks come first and always. Beyond that the selection is
    deliberately spread across projects: three items from the same deadline
    wave is one priority wearing three hats, and it crowds out everything else
    the operator has going on.
    """
    open_tasks = [
        t for t in tasks
        if t.get("status") != "done" and not t.get("archived_at")
    ]
    project_counts = Counter(_project_of(t.get("area")) for t in open_tasks)

    scored = [
        score_task(
            t, today=today, project_counts=project_counts,
            minutes_available=minutes_available, energy=energy,
        )
        for t in open_tasks
    ]
    eligible = [s for s in scored if not s.excluded and s.score > 0]
    eligible.sort(key=lambda s: s.score, reverse=True)

    chosen: list[ScoredTask] = []
    used_projects: set[str] = set()

    for candidate in eligible:
        if candidate.pinned:
            chosen.append(candidate)
            used_projects.add(_project_of(candidate.task.get("area")))

    for candidate in eligible:
        if len(chosen) >= limit:
            break
        if candidate in chosen:
            continue
        project = _project_of(candidate.task.get("area"))
        if project in used_projects:
            continue
        chosen.append(candidate)
        used_projects.add(project)

    # If diversity left slots empty — a backlog dominated by one project will —
    # fill them on score alone rather than showing fewer than asked for.
    if len(chosen) < limit:
        for candidate in eligible:
            if len(chosen) >= limit:
                break
            if candidate not in chosen:
                chosen.append(candidate)

    return chosen[:limit]
