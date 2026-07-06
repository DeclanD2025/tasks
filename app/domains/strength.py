"""Strength-training command centre for ORION web.

This module owns the persistent strength tracker: seeded exercise database,
templates, active workouts, set logging, history, and deterministic analytics.
It deliberately returns plain dictionaries so the web layer stays thin.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from math import ceil

from sqlalchemy import and_, desc, func, or_, select

from app.db.database import session_scope
from app.db.models import (
    StrengthExercise,
    StrengthPersonalRecord,
    StrengthSetEntry,
    StrengthTemplateExercise,
    StrengthWorkout,
    StrengthWorkoutExercise,
    StrengthWorkoutTemplate,
    utcnow,
)

MUSCLE_GROUPS = (
    "Chest",
    "Back",
    "Shoulders",
    "Biceps",
    "Triceps",
    "Quads",
    "Hamstrings",
    "Glutes",
    "Calves",
    "Core",
    "Full body",
)
EQUIPMENT = (
    "Barbell",
    "Dumbbell",
    "Machine",
    "Cable",
    "Bodyweight",
    "Kettlebell",
    "Smith machine",
    "Plate loaded",
)
SET_TYPES = ("warm-up", "working", "drop", "failure")


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _volume(weight: float | None, reps: int | None) -> float:
    return float(weight or 0) * float(reps or 0)


def _e1rm(weight: float | None, reps: int | None) -> float:
    if not weight or not reps:
        return 0.0
    return float(weight) * (1.0 + min(int(reps), 30) / 30.0)


def _ago(day: date | None) -> str:
    if day is None:
        return "never"
    diff = (date.today() - day).days
    if diff <= 0:
        return "today"
    if diff == 1:
        return "yesterday"
    return f"{diff} days ago"


EXERCISE_SEED: tuple[tuple[str, str, list[str], str, str, str, bool, int, int], ...] = (
    ("Bench Press", "Chest", ["Triceps", "Shoulders"], "Barbell", "horizontal push", "compound", False, 4, 6),
    ("Incline Bench Press", "Chest", ["Shoulders", "Triceps"], "Barbell", "incline push", "compound", False, 4, 6),
    ("Dumbbell Bench Press", "Chest", ["Triceps"], "Dumbbell", "horizontal push", "compound", False, 3, 8),
    ("Incline Dumbbell Press", "Chest", ["Shoulders"], "Dumbbell", "incline push", "compound", False, 4, 8),
    ("Chest Press Machine", "Chest", ["Triceps"], "Machine", "horizontal push", "machine", False, 3, 10),
    ("Pec Deck", "Chest", [], "Machine", "fly", "isolation", False, 3, 12),
    ("Cable Fly", "Chest", [], "Cable", "fly", "isolation", False, 3, 12),
    ("Low Cable Fly", "Chest", [], "Cable", "fly", "isolation", False, 3, 12),
    ("Push-up", "Chest", ["Triceps", "Core"], "Bodyweight", "horizontal push", "compound", False, 3, 12),
    ("Dip", "Chest", ["Triceps"], "Bodyweight", "vertical push", "compound", False, 3, 8),
    ("Smith Machine Bench Press", "Chest", ["Triceps"], "Smith machine", "horizontal push", "compound", False, 4, 8),
    ("Pull-up", "Back", ["Biceps"], "Bodyweight", "vertical pull", "compound", False, 4, 6),
    ("Chin-up", "Back", ["Biceps"], "Bodyweight", "vertical pull", "compound", False, 4, 6),
    ("Lat Pulldown", "Back", ["Biceps"], "Machine", "vertical pull", "compound", False, 4, 10),
    ("Seated Cable Row", "Back", ["Biceps"], "Cable", "horizontal pull", "compound", False, 4, 10),
    ("Barbell Row", "Back", ["Biceps", "Hamstrings"], "Barbell", "horizontal pull", "compound", False, 4, 8),
    ("Dumbbell Row", "Back", ["Biceps"], "Dumbbell", "horizontal pull", "compound", True, 3, 10),
    ("Chest Supported Row", "Back", ["Biceps"], "Machine", "horizontal pull", "compound", False, 4, 10),
    ("T-Bar Row", "Back", ["Biceps"], "Plate loaded", "horizontal pull", "compound", False, 4, 8),
    ("Machine Row", "Back", ["Biceps"], "Machine", "horizontal pull", "compound", False, 3, 10),
    ("Single Arm Cable Row", "Back", ["Biceps"], "Cable", "horizontal pull", "compound", True, 3, 10),
    ("Straight Arm Pulldown", "Back", [], "Cable", "shoulder extension", "isolation", False, 3, 12),
    ("Deadlift", "Hamstrings", ["Glutes", "Back"], "Barbell", "hinge", "compound", False, 3, 5),
    ("Romanian Deadlift", "Hamstrings", ["Glutes", "Back"], "Barbell", "hinge", "compound", False, 4, 8),
    ("Dumbbell Romanian Deadlift", "Hamstrings", ["Glutes"], "Dumbbell", "hinge", "compound", False, 3, 10),
    ("Good Morning", "Hamstrings", ["Glutes", "Back"], "Barbell", "hinge", "compound", False, 3, 8),
    ("Back Extension", "Hamstrings", ["Glutes"], "Bodyweight", "hinge", "accessory", False, 3, 12),
    ("Squat", "Quads", ["Glutes", "Core"], "Barbell", "squat", "compound", False, 4, 6),
    ("Front Squat", "Quads", ["Glutes", "Core"], "Barbell", "squat", "compound", False, 4, 5),
    ("Leg Press", "Quads", ["Glutes"], "Plate loaded", "squat", "compound", False, 4, 10),
    ("Hack Squat", "Quads", ["Glutes"], "Machine", "squat", "compound", False, 4, 8),
    ("Smith Machine Squat", "Quads", ["Glutes"], "Smith machine", "squat", "compound", False, 4, 8),
    ("Bulgarian Split Squat", "Quads", ["Glutes"], "Dumbbell", "lunge", "compound", True, 3, 8),
    ("Walking Lunge", "Quads", ["Glutes"], "Dumbbell", "lunge", "compound", True, 3, 10),
    ("Leg Extension", "Quads", [], "Machine", "knee extension", "isolation", False, 3, 12),
    ("Leg Curl", "Hamstrings", [], "Machine", "knee flexion", "isolation", False, 3, 12),
    ("Seated Leg Curl", "Hamstrings", [], "Machine", "knee flexion", "isolation", False, 3, 12),
    ("Hip Thrust", "Glutes", ["Hamstrings"], "Barbell", "hip extension", "compound", False, 4, 8),
    ("Glute Bridge", "Glutes", ["Hamstrings"], "Barbell", "hip extension", "compound", False, 3, 10),
    ("Cable Kickback", "Glutes", [], "Cable", "hip extension", "isolation", True, 3, 12),
    ("Calf Raise", "Calves", [], "Machine", "plantar flexion", "isolation", False, 4, 12),
    ("Seated Calf Raise", "Calves", [], "Machine", "plantar flexion", "isolation", False, 4, 12),
    ("Standing Calf Raise", "Calves", [], "Machine", "plantar flexion", "isolation", False, 4, 12),
    ("Shoulder Press", "Shoulders", ["Triceps"], "Barbell", "vertical push", "compound", False, 4, 6),
    ("Dumbbell Shoulder Press", "Shoulders", ["Triceps"], "Dumbbell", "vertical push", "compound", False, 4, 8),
    ("Machine Shoulder Press", "Shoulders", ["Triceps"], "Machine", "vertical push", "compound", False, 3, 10),
    ("Arnold Press", "Shoulders", ["Triceps"], "Dumbbell", "vertical push", "compound", False, 3, 10),
    ("Lateral Raise", "Shoulders", [], "Dumbbell", "abduction", "isolation", False, 4, 12),
    ("Cable Lateral Raise", "Shoulders", [], "Cable", "abduction", "isolation", True, 3, 12),
    ("Rear Delt Fly", "Shoulders", ["Back"], "Dumbbell", "horizontal abduction", "isolation", False, 3, 12),
    ("Reverse Pec Deck", "Shoulders", ["Back"], "Machine", "horizontal abduction", "isolation", False, 3, 12),
    ("Face Pull", "Shoulders", ["Back"], "Cable", "external rotation", "accessory", False, 3, 15),
    ("Upright Row", "Shoulders", ["Traps"], "Barbell", "pull", "compound", False, 3, 10),
    ("Shrug", "Shoulders", ["Back"], "Dumbbell", "elevation", "isolation", False, 3, 12),
    ("Bicep Curl", "Biceps", [], "Dumbbell", "elbow flexion", "isolation", False, 3, 10),
    ("Hammer Curl", "Biceps", ["Forearms"], "Dumbbell", "elbow flexion", "isolation", False, 3, 10),
    ("Preacher Curl", "Biceps", [], "Machine", "elbow flexion", "isolation", False, 3, 10),
    ("Cable Curl", "Biceps", [], "Cable", "elbow flexion", "isolation", False, 3, 12),
    ("EZ Bar Curl", "Biceps", [], "Barbell", "elbow flexion", "isolation", False, 3, 10),
    ("Incline Dumbbell Curl", "Biceps", [], "Dumbbell", "elbow flexion", "isolation", False, 3, 10),
    ("Concentration Curl", "Biceps", [], "Dumbbell", "elbow flexion", "isolation", True, 3, 10),
    ("Tricep Pushdown", "Triceps", [], "Cable", "elbow extension", "isolation", False, 3, 12),
    ("Overhead Tricep Extension", "Triceps", [], "Cable", "elbow extension", "isolation", False, 3, 12),
    ("Skullcrusher", "Triceps", [], "Barbell", "elbow extension", "isolation", False, 3, 10),
    ("Close Grip Bench Press", "Triceps", ["Chest"], "Barbell", "horizontal push", "compound", False, 3, 8),
    ("Tricep Dip", "Triceps", ["Chest"], "Bodyweight", "vertical push", "compound", False, 3, 8),
    ("Cable Overhead Extension", "Triceps", [], "Cable", "elbow extension", "isolation", False, 3, 12),
    ("Rope Pushdown", "Triceps", [], "Cable", "elbow extension", "isolation", False, 3, 12),
    ("Plank", "Core", [], "Bodyweight", "anti-extension", "core", False, 3, 45),
    ("Cable Crunch", "Core", [], "Cable", "spinal flexion", "core", False, 3, 12),
    ("Hanging Leg Raise", "Core", [], "Bodyweight", "hip flexion", "core", False, 3, 10),
    ("Ab Wheel Rollout", "Core", [], "Bodyweight", "anti-extension", "core", False, 3, 8),
    ("Russian Twist", "Core", [], "Kettlebell", "rotation", "core", False, 3, 16),
    ("Pallof Press", "Core", [], "Cable", "anti-rotation", "core", True, 3, 12),
    ("Farmer Carry", "Full body", ["Core", "Back"], "Dumbbell", "carry", "loaded carry", False, 3, 30),
    ("Kettlebell Swing", "Full body", ["Glutes", "Hamstrings"], "Kettlebell", "hinge", "power", False, 3, 15),
    ("Goblet Squat", "Quads", ["Glutes", "Core"], "Kettlebell", "squat", "compound", False, 3, 10),
    ("Clean and Press", "Full body", ["Shoulders", "Glutes"], "Barbell", "power", "compound", False, 3, 5),
    ("Power Clean", "Full body", ["Glutes", "Back"], "Barbell", "power", "compound", False, 3, 3),
    ("Landmine Press", "Shoulders", ["Chest", "Triceps"], "Plate loaded", "press", "compound", True, 3, 8),
    ("Landmine Row", "Back", ["Biceps"], "Plate loaded", "row", "compound", True, 3, 10),
    ("Step-up", "Quads", ["Glutes"], "Dumbbell", "lunge", "compound", True, 3, 10),
    ("Sled Push", "Full body", ["Quads", "Glutes"], "Plate loaded", "carry", "conditioning", False, 4, 20),
)


TEMPLATE_SEED: dict[str, list[tuple[str, int, int]]] = {
    "Upper Body Accessories": [
        ("Incline Dumbbell Press", 4, 8),
        ("Lat Pulldown", 4, 10),
        ("Dumbbell Shoulder Press", 4, 8),
        ("Bicep Curl", 4, 10),
        ("Hammer Curl", 4, 10),
        ("Tricep Pushdown", 4, 12),
    ],
    "Lower Body": [("Squat", 4, 6), ("Romanian Deadlift", 4, 8), ("Leg Press", 4, 10), ("Leg Curl", 3, 12), ("Calf Raise", 4, 12)],
    "Push": [("Bench Press", 4, 6), ("Incline Dumbbell Press", 3, 8), ("Shoulder Press", 3, 6), ("Lateral Raise", 4, 12), ("Tricep Pushdown", 3, 12)],
    "Pull": [("Pull-up", 4, 6), ("Barbell Row", 4, 8), ("Lat Pulldown", 3, 10), ("Face Pull", 3, 15), ("Hammer Curl", 3, 10)],
    "Legs": [("Squat", 4, 6), ("Hip Thrust", 4, 8), ("Leg Extension", 3, 12), ("Leg Curl", 3, 12), ("Standing Calf Raise", 4, 12)],
    "Full Body": [("Squat", 3, 6), ("Bench Press", 3, 6), ("Seated Cable Row", 3, 10), ("Romanian Deadlift", 3, 8), ("Plank", 3, 45)],
    "Chest & Triceps": [("Bench Press", 4, 6), ("Incline Dumbbell Press", 4, 8), ("Pec Deck", 3, 12), ("Tricep Pushdown", 4, 12), ("Overhead Tricep Extension", 3, 12)],
    "Back & Biceps": [("Lat Pulldown", 4, 10), ("Seated Cable Row", 4, 10), ("Chest Supported Row", 3, 10), ("Bicep Curl", 3, 10), ("Hammer Curl", 3, 10)],
    "Shoulders & Arms": [("Dumbbell Shoulder Press", 4, 8), ("Lateral Raise", 4, 12), ("Rear Delt Fly", 3, 12), ("Bicep Curl", 3, 10), ("Skullcrusher", 3, 10)],
}


def ensure_seeded() -> None:
    with session_scope() as s:
        existing = set(s.scalars(select(StrengthExercise.slug)).all())
        for row in EXERCISE_SEED:
            name, primary, secondary, equipment, movement, category, unilateral, sets, reps = row
            slug = _slug(name)
            if slug in existing:
                continue
            s.add(
                StrengthExercise(
                    slug=slug,
                    name=name,
                    primary_muscle=primary,
                    secondary_muscles=secondary,
                    equipment=equipment,
                    movement_pattern=movement,
                    category=category,
                    unilateral=unilateral,
                    default_sets=sets,
                    default_reps=reps,
                )
            )
        s.flush()
        by_name = {e.name: e for e in s.scalars(select(StrengthExercise)).all()}
        existing_templates = set(s.scalars(select(StrengthWorkoutTemplate.name)).all())
        for idx, (name, exercises) in enumerate(TEMPLATE_SEED.items(), start=1):
            if name in existing_templates:
                continue
            template = StrengthWorkoutTemplate(
                name=name,
                description=f"{name} template seeded for quick one-handed starts.",
            )
            s.add(template)
            s.flush()
            for order, (exercise_name, sets, reps) in enumerate(exercises, start=1):
                ex = by_name.get(exercise_name)
                if not ex:
                    continue
                s.add(
                    StrengthTemplateExercise(
                        template_id=template.id,
                        exercise_id=ex.id,
                        sort_order=order,
                        target_sets=sets,
                        target_reps=reps,
                    )
                )


def _exercise_dict(ex: StrengthExercise) -> dict:
    return {
        "id": ex.id,
        "name": ex.name,
        "primary": ex.primary_muscle,
        "secondary": ex.secondary_muscles or [],
        "equipment": ex.equipment,
        "movement": ex.movement_pattern,
        "category": ex.category,
        "unilateral": ex.unilateral,
        "default_sets": ex.default_sets,
        "default_reps": ex.default_reps,
        "favorite": ex.favorite,
        "is_custom": ex.is_custom,
        "glyph": _glyph(ex.primary_muscle),
    }


def _glyph(muscle: str) -> str:
    return {
        "Chest": "◇",
        "Back": "⬡",
        "Shoulders": "△",
        "Biceps": "⌁",
        "Triceps": "⌯",
        "Quads": "▰",
        "Hamstrings": "▱",
        "Glutes": "◖",
        "Calves": "▴",
        "Core": "◎",
        "Full body": "✦",
    }.get(muscle, "◇")


def _set_dict(row: StrengthSetEntry) -> dict:
    return {
        "id": row.id,
        "set_number": row.set_number,
        "weight": row.weight_kg,
        "reps": row.reps,
        "rpe": row.rpe,
        "set_type": row.set_type,
        "completed": bool(row.completed),
        "volume": _volume(row.weight_kg, row.reps),
        "e1rm": _e1rm(row.weight_kg, row.reps),
    }


def templates() -> list[dict]:
    ensure_seeded()
    with session_scope() as s:
        rows = s.scalars(select(StrengthWorkoutTemplate).order_by(StrengthWorkoutTemplate.name)).all()
    out = []
    for row in rows:
        # SQLAlchemy tuple dict above loses the third item; compute simply.
        detail = template_detail(row.id)
        out.append({
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "exercise_count": detail["exercise_count"],
            "set_count": detail["set_count"],
            "muscles": detail["muscles"],
        })
    return out


def template_detail(template_id: int) -> dict:
    ensure_seeded()
    with session_scope() as s:
        template = s.get(StrengthWorkoutTemplate, template_id)
        if not template:
            raise ValueError("Template not found")
        rows = s.execute(
            select(StrengthTemplateExercise, StrengthExercise)
            .join(StrengthExercise, StrengthExercise.id == StrengthTemplateExercise.exercise_id)
            .where(StrengthTemplateExercise.template_id == template_id)
            .order_by(StrengthTemplateExercise.sort_order)
        ).all()
    exercises = [
        {
            **_exercise_dict(ex),
            "target_sets": te.target_sets,
            "target_reps": te.target_reps,
            "notes": te.notes,
        }
        for te, ex in rows
    ]
    muscles = sorted({ex["primary"] for ex in exercises})
    return {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "exercise_count": len(exercises),
        "set_count": sum(ex["target_sets"] for ex in exercises),
        "exercises": exercises,
        "muscles": muscles,
    }


def active_workout(user_id: int) -> dict | None:
    ensure_seeded()
    with session_scope() as s:
        row = s.scalars(
            select(StrengthWorkout)
            .where(StrengthWorkout.user_id == user_id, StrengthWorkout.status == "active")
            .order_by(desc(StrengthWorkout.started_at))
        ).first()
        return workout_detail(user_id, row.id) if row else None


def start_workout(user_id: int, *, template_id: int | None = None, name: str = "") -> int:
    ensure_seeded()
    with session_scope() as s:
        active = s.scalars(
            select(StrengthWorkout.id).where(
                StrengthWorkout.user_id == user_id,
                StrengthWorkout.status == "active",
            )
        ).first()
        if active:
            return active
        template = s.get(StrengthWorkoutTemplate, template_id) if template_id else None
        workout = StrengthWorkout(
            user_id=user_id,
            template_id=template.id if template else None,
            name=(name.strip() or (template.name if template else "Strength Workout"))[:160],
        )
        s.add(workout)
        s.flush()
        if template:
            rows = s.scalars(
                select(StrengthTemplateExercise)
                .where(StrengthTemplateExercise.template_id == template.id)
                .order_by(StrengthTemplateExercise.sort_order)
            ).all()
            for row in rows:
                _add_exercise_rows(s, workout.id, row.exercise_id, row.target_sets, row.target_reps)
        return workout.id


def _add_exercise_rows(
    s, workout_id: int, exercise_id: int, target_sets: int | None = None, target_reps: int | None = None
) -> int:
    ex = s.get(StrengthExercise, exercise_id)
    order = (
        s.scalar(
            select(func.max(StrengthWorkoutExercise.sort_order)).where(
                StrengthWorkoutExercise.workout_id == workout_id
            )
        )
        or 0
    ) + 1
    row = StrengthWorkoutExercise(
        workout_id=workout_id,
        exercise_id=exercise_id,
        sort_order=order,
        target_sets=target_sets or ex.default_sets,
        target_reps=target_reps or ex.default_reps,
    )
    s.add(row)
    s.flush()
    last = _last_exercise_sets_in_session(s, workout_id, exercise_id)
    planned = last or [
        {"weight": None, "reps": row.target_reps, "set_type": "working"}
        for _ in range(max(1, row.target_sets))
    ]
    for idx, item in enumerate(planned[:8], start=1):
        s.add(
            StrengthSetEntry(
                workout_exercise_id=row.id,
                set_number=idx,
                weight_kg=item.get("weight"),
                reps=item.get("reps"),
                set_type=item.get("set_type", "working"),
            )
        )
    return row.id


def add_exercise_to_workout(user_id: int, workout_id: int, exercise_id: int) -> int:
    with session_scope() as s:
        workout = s.get(StrengthWorkout, workout_id)
        if not workout or workout.user_id != user_id or workout.status != "active":
            raise ValueError("Workout not available")
        existing = s.scalars(
            select(StrengthWorkoutExercise.id).where(
                StrengthWorkoutExercise.workout_id == workout_id,
                StrengthWorkoutExercise.exercise_id == exercise_id,
            )
        ).first()
        if existing:
            return existing
        workout.updated_at = utcnow()
        return _add_exercise_rows(s, workout_id, exercise_id)


def create_custom_exercise(
    *, name: str, primary_muscle: str, equipment: str, default_sets: int = 3, default_reps: int = 8
) -> int:
    with session_scope() as s:
        slug = _slug(name)
        existing = s.scalars(select(StrengthExercise.id).where(StrengthExercise.slug == slug)).first()
        if existing:
            return existing
        row = StrengthExercise(
            slug=slug,
            name=name.strip()[:160],
            primary_muscle=primary_muscle if primary_muscle in MUSCLE_GROUPS else "Full body",
            secondary_muscles=[],
            equipment=equipment if equipment in EQUIPMENT else "Dumbbell",
            movement_pattern="custom",
            category="strength",
            default_sets=max(1, min(8, int(default_sets or 3))),
            default_reps=max(1, min(50, int(default_reps or 8))),
            is_custom=True,
        )
        s.add(row)
        s.flush()
        return row.id


def _last_exercise_sets_in_session(s, workout_id: int, exercise_id: int) -> list[dict]:
    workout = s.get(StrengthWorkout, workout_id)
    if not workout:
        return []
    previous = s.execute(
        select(StrengthWorkout, StrengthWorkoutExercise)
        .join(StrengthWorkoutExercise, StrengthWorkoutExercise.workout_id == StrengthWorkout.id)
        .where(
            StrengthWorkout.user_id == workout.user_id,
            StrengthWorkout.status == "completed",
            StrengthWorkoutExercise.exercise_id == exercise_id,
        )
        .order_by(desc(StrengthWorkout.finished_at), desc(StrengthWorkout.started_at))
        .limit(1)
    ).first()
    if not previous:
        return []
    _, we = previous
    sets = s.scalars(
        select(StrengthSetEntry)
        .where(StrengthSetEntry.workout_exercise_id == we.id, StrengthSetEntry.completed == True)
        .order_by(StrengthSetEntry.set_number)
    ).all()
    return [
        {"weight": row.weight_kg, "reps": row.reps, "set_type": row.set_type}
        for row in sets
    ]


def update_set(
    user_id: int,
    set_id: int,
    *,
    weight: str = "",
    reps: str = "",
    rpe: str = "",
    set_type: str = "working",
    completed: bool = False,
) -> None:
    with session_scope() as s:
        row = s.get(StrengthSetEntry, set_id)
        if not row:
            return
        we = s.get(StrengthWorkoutExercise, row.workout_exercise_id)
        workout = s.get(StrengthWorkout, we.workout_id) if we else None
        if not workout or workout.user_id != user_id or workout.status != "active":
            return
        row.weight_kg = float(weight) if str(weight).strip() else None
        row.reps = int(float(reps)) if str(reps).strip() else None
        row.rpe = float(rpe) if str(rpe).strip() else None
        row.set_type = set_type if set_type in SET_TYPES else "working"
        row.completed = bool(completed)
        row.completed_at = utcnow() if completed and row.completed_at is None else row.completed_at
        row.updated_at = utcnow()
        workout.updated_at = utcnow()
        if completed:
            nxt = s.scalars(
                select(StrengthSetEntry).where(
                    StrengthSetEntry.workout_exercise_id == row.workout_exercise_id,
                    StrengthSetEntry.set_number == row.set_number + 1,
                )
            ).first()
            if nxt and not nxt.completed:
                if nxt.weight_kg is None:
                    nxt.weight_kg = row.weight_kg
                if nxt.reps is None:
                    nxt.reps = row.reps


def add_set(user_id: int, workout_exercise_id: int) -> int:
    with session_scope() as s:
        we = s.get(StrengthWorkoutExercise, workout_exercise_id)
        workout = s.get(StrengthWorkout, we.workout_id) if we else None
        if not workout or workout.user_id != user_id or workout.status != "active":
            raise ValueError("Exercise not available")
        last = s.scalars(
            select(StrengthSetEntry)
            .where(StrengthSetEntry.workout_exercise_id == workout_exercise_id)
            .order_by(desc(StrengthSetEntry.set_number))
        ).first()
        row = StrengthSetEntry(
            workout_exercise_id=workout_exercise_id,
            set_number=(last.set_number + 1) if last else 1,
            weight_kg=last.weight_kg if last else None,
            reps=last.reps if last else we.target_reps,
            set_type=last.set_type if last else "working",
        )
        s.add(row)
        workout.updated_at = utcnow()
        s.flush()
        return row.id


def apply_last_workout(user_id: int, workout_exercise_id: int) -> None:
    with session_scope() as s:
        we = s.get(StrengthWorkoutExercise, workout_exercise_id)
        workout = s.get(StrengthWorkout, we.workout_id) if we else None
        if not workout or workout.user_id != user_id or workout.status != "active":
            return
        previous = _last_exercise_sets_in_session(s, workout.id, we.exercise_id)
        if not previous:
            return
        existing = s.scalars(
            select(StrengthSetEntry).where(
                StrengthSetEntry.workout_exercise_id == workout_exercise_id
            )
        ).all()
        for row in existing:
            s.delete(row)
        s.flush()
        for idx, item in enumerate(previous, start=1):
            s.add(
                StrengthSetEntry(
                    workout_exercise_id=workout_exercise_id,
                    set_number=idx,
                    weight_kg=item.get("weight"),
                    reps=item.get("reps"),
                    set_type=item.get("set_type", "working"),
                )
            )


def finish_workout(user_id: int, workout_id: int, notes: str = "") -> None:
    with session_scope() as s:
        workout = s.get(StrengthWorkout, workout_id)
        if not workout or workout.user_id != user_id:
            return
        workout.status = "completed"
        workout.finished_at = utcnow()
        workout.notes = notes.strip()
        workout.updated_at = utcnow()
        _record_prs(s, user_id, workout_id)


def discard_workout(user_id: int, workout_id: int) -> None:
    with session_scope() as s:
        workout = s.get(StrengthWorkout, workout_id)
        if workout and workout.user_id == user_id:
            workout.status = "discarded"
            workout.updated_at = utcnow()


def _record_prs(s, user_id: int, workout_id: int) -> None:
    rows = s.execute(
        select(StrengthWorkoutExercise.exercise_id, StrengthSetEntry)
        .join(StrengthSetEntry, StrengthSetEntry.workout_exercise_id == StrengthWorkoutExercise.id)
        .where(
            StrengthWorkoutExercise.workout_id == workout_id,
            StrengthSetEntry.completed == True,
            StrengthSetEntry.weight_kg.is_not(None),
            StrengthSetEntry.reps.is_not(None),
        )
    ).all()
    for exercise_id, set_row in rows:
        for record_type, value in (
            ("top_set", float(set_row.weight_kg or 0)),
            ("e1rm", _e1rm(set_row.weight_kg, set_row.reps)),
        ):
            best = s.scalar(
                select(func.max(StrengthPersonalRecord.value)).where(
                    StrengthPersonalRecord.user_id == user_id,
                    StrengthPersonalRecord.exercise_id == exercise_id,
                    StrengthPersonalRecord.record_type == record_type,
                )
            ) or 0
            if value > best:
                s.add(
                    StrengthPersonalRecord(
                        user_id=user_id,
                        exercise_id=exercise_id,
                        workout_id=workout_id,
                        set_entry_id=set_row.id,
                        record_type=record_type,
                        value=value,
                    )
                )


def workout_detail(user_id: int, workout_id: int) -> dict:
    ensure_seeded()
    with session_scope() as s:
        workout = s.get(StrengthWorkout, workout_id)
        if not workout or workout.user_id != user_id:
            raise ValueError("Workout not found")
        rows = s.execute(
            select(StrengthWorkoutExercise, StrengthExercise)
            .join(StrengthExercise, StrengthExercise.id == StrengthWorkoutExercise.exercise_id)
            .where(StrengthWorkoutExercise.workout_id == workout_id)
            .order_by(StrengthWorkoutExercise.sort_order)
        ).all()
        we_ids = [we.id for we, _ in rows]
        set_rows = s.scalars(
            select(StrengthSetEntry)
            .where(StrengthSetEntry.workout_exercise_id.in_(we_ids))
            .order_by(StrengthSetEntry.workout_exercise_id, StrengthSetEntry.set_number)
        ).all() if we_ids else []
        last_by_ex = {ex.id: _last_performed(s, user_id, ex.id, exclude_workout_id=workout_id) for _, ex in rows}
    sets_by_we = defaultdict(list)
    for row in set_rows:
        sets_by_we[row.workout_exercise_id].append(_set_dict(row))
    exercises = []
    for we, ex in rows:
        sets = sets_by_we.get(we.id, [])
        exercises.append({
            "id": we.id,
            "exercise": _exercise_dict(ex),
            "target_sets": we.target_sets,
            "target_reps": we.target_reps,
            "notes": we.notes,
            "sets": sets,
            "completed_sets": sum(1 for item in sets if item["completed"]),
            "volume": sum(item["volume"] for item in sets if item["completed"]),
            "last": last_by_ex.get(ex.id),
        })
    completed_sets = sum(ex["completed_sets"] for ex in exercises)
    total_volume = sum(ex["volume"] for ex in exercises)
    duration = _duration_minutes(workout.started_at, workout.finished_at or datetime.now())
    return {
        "id": workout.id,
        "template_id": workout.template_id,
        "name": workout.name,
        "status": workout.status,
        "started_at": workout.started_at,
        "finished_at": workout.finished_at,
        "duration_minutes": duration,
        "default_rest_seconds": workout.default_rest_seconds,
        "notes": workout.notes,
        "exercises": exercises,
        "exercise_count": len(exercises),
        "completed_sets": completed_sets,
        "total_sets": sum(len(ex["sets"]) for ex in exercises),
        "total_volume": total_volume,
        "muscles": sorted({ex["exercise"]["primary"] for ex in exercises}),
    }


def _duration_minutes(start: datetime, end: datetime | None) -> int:
    return max(0, int(((end or datetime.now()) - start.replace(tzinfo=None)).total_seconds() // 60))


def _last_performed(s, user_id: int, exercise_id: int, exclude_workout_id: int | None = None) -> dict | None:
    filters = [
        StrengthWorkout.user_id == user_id,
        StrengthWorkout.status == "completed",
        StrengthWorkoutExercise.exercise_id == exercise_id,
    ]
    if exclude_workout_id:
        filters.append(StrengthWorkout.id != exclude_workout_id)
    row = s.execute(
        select(StrengthWorkout, StrengthWorkoutExercise)
        .join(StrengthWorkoutExercise, StrengthWorkoutExercise.workout_id == StrengthWorkout.id)
        .where(and_(*filters))
        .order_by(desc(StrengthWorkout.finished_at), desc(StrengthWorkout.started_at))
        .limit(1)
    ).first()
    if not row:
        return None
    workout, we = row
    sets = s.scalars(
        select(StrengthSetEntry)
        .where(StrengthSetEntry.workout_exercise_id == we.id, StrengthSetEntry.completed == True)
        .order_by(StrengthSetEntry.set_number)
    ).all()
    set_dicts = [_set_dict(item) for item in sets]
    return {
        "workout_id": workout.id,
        "workout_name": workout.name,
        "day": (workout.finished_at or workout.started_at).date(),
        "date_label": (workout.finished_at or workout.started_at).strftime("%d %b"),
        "sets": set_dicts,
        "top_set": max((item["weight"] or 0 for item in set_dicts), default=0),
        "volume": sum(item["volume"] for item in set_dicts),
        "e1rm": max((item["e1rm"] for item in set_dicts), default=0),
        "notes": workout.notes,
    }


def exercise_picker(
    user_id: int,
    *,
    q: str = "",
    muscle: str = "",
    equipment: str = "",
    favorites: bool = False,
    template_id: int | None = None,
) -> dict:
    ensure_seeded()
    with session_scope() as s:
        query = select(StrengthExercise)
        if q.strip():
            like = f"%{q.strip()}%"
            query = query.where(StrengthExercise.name.ilike(like))
        if muscle:
            query = query.where(StrengthExercise.primary_muscle == muscle)
        if equipment:
            query = query.where(StrengthExercise.equipment == equipment)
        if favorites:
            query = query.where(StrengthExercise.favorite == True)
        rows = s.scalars(query.order_by(StrengthExercise.primary_muscle, StrengthExercise.name)).all()
        recent_ids = [
            item[0]
            for item in s.execute(
                select(StrengthWorkoutExercise.exercise_id)
                .join(StrengthWorkout, StrengthWorkout.id == StrengthWorkoutExercise.workout_id)
                .where(StrengthWorkout.user_id == user_id)
                .order_by(desc(StrengthWorkout.started_at))
                .limit(12)
            ).all()
        ]
        template_ids = set()
        if template_id:
            template_ids = set(
                s.scalars(
                    select(StrengthTemplateExercise.exercise_id).where(
                        StrengthTemplateExercise.template_id == template_id
                    )
                ).all()
            )
    recent_set = set(recent_ids)
    out = []
    for row in rows:
        item = _exercise_dict(row)
        item["recent"] = row.id in recent_set
        item["template"] = row.id in template_ids
        item["rank"] = (0 if item["template"] else 1) + (0 if item["recent"] else 2)
        out.append(item)
    out.sort(key=lambda item: (item["rank"], item["primary"], item["name"]))
    return {
        "exercises": out,
        "muscles": MUSCLE_GROUPS,
        "equipment": EQUIPMENT,
        "q": q,
        "muscle": muscle,
        "selected_equipment": equipment,
        "favorites": favorites,
    }


def toggle_favorite(exercise_id: int) -> None:
    with session_scope() as s:
        row = s.get(StrengthExercise, exercise_id)
        if row:
            row.favorite = not bool(row.favorite)


def dashboard(user_id: int) -> dict:
    ensure_seeded()
    since = date.today() - timedelta(days=30)
    week_start = date.today() - timedelta(days=date.today().weekday())
    workouts = history(user_id, since=since)
    week = [w for w in workouts if w["day"] >= week_start]
    muscles = Counter()
    trained_days: dict[str, date] = {}
    for w in workouts:
        for m in w["muscles"]:
            muscles[m] += 1
            trained_days[m] = max(trained_days.get(m, date.min), w["day"])
    next_muscle = max(
        MUSCLE_GROUPS,
        key=lambda m: (date.today() - trained_days.get(m, date.today() - timedelta(days=30))).days,
    )
    last = workouts[0] if workouts else None
    heatmap = _heatmap(workouts)
    prs = recent_prs(user_id, limit=5)
    progressions = strength_progressions(user_id)
    weekly_volume = sum(w["volume"] for w in week)
    prev_volume = _volume_between(user_id, week_start - timedelta(days=7), week_start - timedelta(days=1))
    volume_delta = ((weekly_volume - prev_volume) / prev_volume * 100) if prev_volume else None
    neglected = [
        {"muscle": m, "days": (date.today() - trained_days.get(m, date.today() - timedelta(days=30))).days}
        for m in MUSCLE_GROUPS
        if m != "Full body"
    ]
    neglected.sort(key=lambda item: item["days"], reverse=True)
    return {
        "active": active_workout(user_id),
        "week_sessions": len(week),
        "week_sets": sum(w["sets"] for w in week),
        "week_volume": weekly_volume,
        "last_workout": last,
        "last_trained_label": _last_trained_label(last),
        "next_muscle": next_muscle,
        "muscle_frequency": [{"muscle": m, "count": muscles.get(m, 0)} for m in MUSCLE_GROUPS],
        "days_since": neglected,
        "heatmap": heatmap,
        "recent_prs": prs,
        "progressions": progressions,
        "volume_delta": volume_delta,
        "balance_note": _balance_note(neglected, len(workouts)),
        "empty": not workouts,
        "templates": templates()[:9],
    }


def _last_trained_label(last: dict | None) -> str:
    if not last:
        return "No completed strength sessions yet"
    muscles = " & ".join(last["muscles"][:2]) if last["muscles"] else "Strength"
    return f"{muscles} · {_ago(last['day'])}"


def _balance_note(neglected: list[dict], workout_count: int) -> str:
    if workout_count < 3:
        return "Complete 3 sessions to unlock strength trends."
    top = neglected[0]
    if top["days"] >= 7:
        return f"{top['muscle']} has not been trained in {top['days']} days."
    return "Training balance is holding; keep rotating the main patterns."


def _volume_between(user_id: int, start: date, end: date) -> float:
    rows = history(user_id, since=start, until=end)
    return sum(row["volume"] for row in rows)


def _heatmap(workouts: list[dict]) -> list[dict]:
    by_day = defaultdict(float)
    for w in workouts:
        by_day[w["day"]] += w["volume"]
    start = date.today() - timedelta(days=34)
    out = []
    max_v = max(by_day.values(), default=1)
    for idx in range(35):
        day = start + timedelta(days=idx)
        volume = by_day.get(day, 0.0)
        level = 0 if volume == 0 else max(1, min(4, ceil(volume / max_v * 4)))
        out.append({"day": day, "label": day.strftime("%d %b"), "volume": volume, "level": level})
    return out


def history(user_id: int, *, since: date | None = None, until: date | None = None, limit: int = 60) -> list[dict]:
    ensure_seeded()
    with session_scope() as s:
        query = select(StrengthWorkout).where(
            StrengthWorkout.user_id == user_id,
            StrengthWorkout.status == "completed",
        )
        if since:
            query = query.where(func.date(StrengthWorkout.started_at) >= since.isoformat())
        if until:
            query = query.where(func.date(StrengthWorkout.started_at) <= until.isoformat())
        rows = s.scalars(query.order_by(desc(StrengthWorkout.started_at)).limit(limit)).all()
        ids = [row.id for row in rows]
        ex_rows = s.execute(
            select(StrengthWorkoutExercise, StrengthExercise)
            .join(StrengthExercise, StrengthExercise.id == StrengthWorkoutExercise.exercise_id)
            .where(StrengthWorkoutExercise.workout_id.in_(ids))
        ).all() if ids else []
        set_rows = s.execute(
            select(StrengthWorkoutExercise.workout_id, StrengthSetEntry)
            .join(StrengthSetEntry, StrengthSetEntry.workout_exercise_id == StrengthWorkoutExercise.id)
            .where(StrengthWorkoutExercise.workout_id.in_(ids), StrengthSetEntry.completed == True)
        ).all() if ids else []
    muscles_by_workout = defaultdict(set)
    exercises_by_workout = defaultdict(list)
    for we, ex in ex_rows:
        muscles_by_workout[we.workout_id].add(ex.primary_muscle)
        exercises_by_workout[we.workout_id].append(ex.name)
    set_count = Counter()
    volume = Counter()
    for workout_id, row in set_rows:
        set_count[workout_id] += 1
        volume[workout_id] += _volume(row.weight_kg, row.reps)
    return [
        {
            "id": row.id,
            "name": row.name,
            "day": row.started_at.date(),
            "date_label": row.started_at.strftime("%d %b"),
            "duration": _duration_minutes(row.started_at, row.finished_at),
            "sets": set_count[row.id],
            "volume": float(volume[row.id]),
            "exercises": exercises_by_workout[row.id],
            "exercise_count": len(exercises_by_workout[row.id]),
            "muscles": sorted(muscles_by_workout[row.id]),
        }
        for row in rows
    ]


def recent_prs(user_id: int, limit: int = 8) -> list[dict]:
    with session_scope() as s:
        rows = s.execute(
            select(StrengthPersonalRecord, StrengthExercise)
            .join(StrengthExercise, StrengthExercise.id == StrengthPersonalRecord.exercise_id)
            .where(StrengthPersonalRecord.user_id == user_id)
            .order_by(desc(StrengthPersonalRecord.achieved_at))
            .limit(limit)
        ).all()
    return [
        {
            "exercise": ex.name,
            "type": "Top set" if pr.record_type == "top_set" else "Estimated 1RM",
            "value": pr.value,
            "date": pr.achieved_at.date(),
        }
        for pr, ex in rows
    ]


def strength_progressions(user_id: int, limit: int = 5) -> list[dict]:
    with session_scope() as s:
        rows = s.execute(
            select(StrengthExercise.id, StrengthExercise.name, StrengthWorkout.started_at, StrengthSetEntry)
            .join(StrengthWorkoutExercise, StrengthWorkoutExercise.exercise_id == StrengthExercise.id)
            .join(StrengthWorkout, StrengthWorkout.id == StrengthWorkoutExercise.workout_id)
            .join(StrengthSetEntry, StrengthSetEntry.workout_exercise_id == StrengthWorkoutExercise.id)
            .where(
                StrengthWorkout.user_id == user_id,
                StrengthWorkout.status == "completed",
                StrengthSetEntry.completed == True,
            )
            .order_by(StrengthExercise.name, StrengthWorkout.started_at)
        ).all()
    by_ex = defaultdict(list)
    for ex_id, name, started_at, set_row in rows:
        by_ex[(ex_id, name)].append((started_at.date(), _e1rm(set_row.weight_kg, set_row.reps), set_row.weight_kg or 0))
    out = []
    for (_, name), series in by_ex.items():
        if len(series) < 2:
            continue
        points = [v for _, v, _ in series if v > 0][-8:]
        if not points:
            continue
        delta = points[-1] - points[0]
        out.append({"exercise": name, "points": points, "delta": delta, "top": max(w for _, _, w in series)})
    out.sort(key=lambda item: abs(item["delta"]), reverse=True)
    return out[:limit]


def analytics(user_id: int) -> dict:
    snap = dashboard(user_id)
    workouts = history(user_id, limit=120)
    volume_by_muscle = Counter()
    most_trained = Counter()
    with session_scope() as s:
        rows = s.execute(
            select(StrengthExercise, StrengthSetEntry)
            .join(StrengthWorkoutExercise, StrengthWorkoutExercise.exercise_id == StrengthExercise.id)
            .join(StrengthWorkout, StrengthWorkout.id == StrengthWorkoutExercise.workout_id)
            .join(StrengthSetEntry, StrengthSetEntry.workout_exercise_id == StrengthWorkoutExercise.id)
            .where(
                StrengthWorkout.user_id == user_id,
                StrengthWorkout.status == "completed",
                StrengthSetEntry.completed == True,
            )
        ).all()
    for ex, set_row in rows:
        volume_by_muscle[ex.primary_muscle] += _volume(set_row.weight_kg, set_row.reps)
        most_trained[ex.name] += 1
    return {
        **snap,
        "workouts_per_month": len(workouts),
        "volume_by_muscle": [{"muscle": m, "volume": volume_by_muscle.get(m, 0)} for m in MUSCLE_GROUPS],
        "most_trained": most_trained.most_common(8),
    }


def exercise_detail(user_id: int, exercise_id: int) -> dict:
    ensure_seeded()
    with session_scope() as s:
        ex = s.get(StrengthExercise, exercise_id)
        if not ex:
            raise ValueError("Exercise not found")
        rows = s.execute(
            select(StrengthWorkout, StrengthSetEntry)
            .join(StrengthWorkoutExercise, StrengthWorkoutExercise.workout_id == StrengthWorkout.id)
            .join(StrengthSetEntry, StrengthSetEntry.workout_exercise_id == StrengthWorkoutExercise.id)
            .where(
                StrengthWorkout.user_id == user_id,
                StrengthWorkout.status == "completed",
                StrengthWorkoutExercise.exercise_id == exercise_id,
                StrengthSetEntry.completed == True,
            )
            .order_by(desc(StrengthWorkout.started_at), StrengthSetEntry.set_number)
        ).all()
    by_workout = defaultdict(list)
    workout_meta = {}
    for workout, set_row in rows:
        by_workout[workout.id].append(_set_dict(set_row))
        workout_meta[workout.id] = workout
    workouts = []
    for wid, sets in by_workout.items():
        workout = workout_meta[wid]
        workouts.append({
            "id": wid,
            "name": workout.name,
            "day": workout.started_at.date(),
            "date_label": workout.started_at.strftime("%d %b"),
            "sets": sets,
            "volume": sum(item["volume"] for item in sets),
            "top_set": max((item["weight"] or 0 for item in sets), default=0),
            "e1rm": max((item["e1rm"] for item in sets), default=0),
        })
    workouts.sort(key=lambda item: item["day"], reverse=True)
    best = max((item["e1rm"] for item in workouts), default=0)
    last = workouts[0] if workouts else None
    aim = ""
    if last and last["sets"]:
        top = max(last["sets"], key=lambda item: item["e1rm"])
        aim = f"Aim for {top['weight'] or 0:g}kg x {(top['reps'] or 0) + 1} or add 2.5kg if reps felt clean."
    else:
        aim = "No previous data yet. Set your baseline today."
    return {
        "exercise": _exercise_dict(ex),
        "last": last,
        "last_performed": _ago(last["day"] if last else None),
        "sessions": len(workouts),
        "top_set": max((w["top_set"] for w in workouts), default=0),
        "best_e1rm": best,
        "volume_points": [w["volume"] for w in reversed(workouts[-8:])],
        "e1rm_points": [w["e1rm"] for w in reversed(workouts[-8:])],
        "workouts": workouts,
        "aim": aim,
    }
