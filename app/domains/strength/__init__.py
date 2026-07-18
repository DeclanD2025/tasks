"""Strength training.

The package is split by responsibility rather than by screen:

- ``calc``        — pure maths over plain values. No database, no I/O.
- ``catalog``     — the exercise library: families, variants, classification.
- ``records``     — personal-record detection and invalidation.
- ``progression`` — the transparent rules engine that proposes load changes.
- ``sessions``    — session lifecycle: start, log, correct, finish, resume.
- ``programmes``  — programmes, templates and scheduling.
- ``reporting``   — longitudinal aggregates over completed work. (Named this
  rather than ``analytics`` because ``tracker.analytics()`` already owns that
  name at package level — see the module docstring.)
- ``export``      — analysis-ready CSV/JSON out, and import back in.
- ``tracker``     — the original quick-logging module that backs the Jinja UI.

``tracker`` is re-exported at package level so ``from app.domains import
strength`` keeps working exactly as before for the legacy web routes, which
are still the only shipped strength UI. Nothing in the new modules imports
from it — the dependency runs one way only, so the legacy tracker can be
retired later without unpicking the analytics.
"""

from __future__ import annotations

from app.domains.strength.tracker import *  # noqa: F401,F403  (legacy surface)
from app.domains.strength.tracker import (  # noqa: F401  explicit, for clarity
    SET_TYPES,
    active_workout,
    add_exercise_to_workout,
    add_set,
    analytics,
    apply_last_workout,
    create_custom_exercise,
    dashboard,
    discard_workout,
    ensure_seeded,
    exercise_detail,
    exercise_picker,
    finish_workout,
    history,
    recent_prs,
    start_workout,
    strength_progressions,
    template_detail,
    templates,
    toggle_favorite,
    update_set,
    workout_detail,
)

__all__ = [
    "SET_TYPES",
    "active_workout",
    "add_exercise_to_workout",
    "add_set",
    "analytics",
    "apply_last_workout",
    "create_custom_exercise",
    "dashboard",
    "discard_workout",
    "ensure_seeded",
    "exercise_detail",
    "exercise_picker",
    "finish_workout",
    "history",
    "recent_prs",
    "start_workout",
    "strength_progressions",
    "template_detail",
    "templates",
    "toggle_favorite",
    "update_set",
    "workout_detail",
]
