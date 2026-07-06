"""Nutrition service: logging, day/week snapshots, food library, templates.

All functions take ``user_id`` first and return plain dicts/lists so the web
layer stays thin. Macros are snapshotted onto each ``FoodLog`` at log time —
a later correction to a food improves future logs without rewriting history.
Times are local (this is a personal, single-machine OS): ``day`` boundaries
follow the operator's clock, not UTC.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select

from app.db.database import session_scope
from app.db.models import FoodLog, MealTemplate, NutritionFood, utcnow
from app.domains import settings_service
from app.domains.nutrition import generics, off_client

MEAL_TYPES = ("breakfast", "lunch", "dinner", "snack")

_MACROS = ("calories", "protein", "carbs", "fat", "fibre", "sugar", "saturated_fat", "sodium_mg")
_CORRECTABLE_TEXT = ("name", "brand", "serving_unit")
_CORRECTABLE_NUMBER = ("serving_size", *(f"{macro}_100g" for macro in _MACROS))


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _round1(value: float | None) -> float | None:
    return round(float(value), 1) if value is not None else None


def _meal_or_snack(meal_type: str | None) -> str:
    return meal_type if meal_type in MEAL_TYPES else "snack"


def _meal_for_hour(hour: int) -> str:
    if hour < 11:
        return "breakfast"
    if hour < 15:
        return "lunch"
    if hour < 21:
        return "dinner"
    return "snack"


def _pct(total: float, target: float | None) -> int | None:
    if not target:
        return None
    return max(0, min(100, int(round(total / target * 100))))


def _food_dict(food: NutritionFood) -> dict[str, Any]:
    if food.serving_size:
        serving = f"{food.serving_size:g} g · {food.serving_unit}"
    else:
        serving = food.serving_unit or "per 100 g"
    return {
        "id": food.id,
        "name": food.name,
        "brand": food.brand,
        "barcode": food.barcode,
        "serving_size": food.serving_size,
        "serving_unit": food.serving_unit,
        "serving": serving,
        **{f"{macro}_100g": getattr(food, f"{macro}_100g") for macro in _MACROS},
        "source_provider": food.source_provider,
        "source_confidence": food.source_confidence,
        "saved": bool(food.saved),
        "user_corrected": bool(food.user_corrected),
        "use_count": food.use_count,
    }


def _upsert_food(s, user_id: int, payload: dict) -> NutritionFood:
    """Find-or-create a library row for a provider payload.

    Matched by barcode when present, else (name, brand, provider). Provider
    values refresh the row unless the operator has corrected it — a human fix
    must never be clobbered by a re-scan.
    """
    barcode = str(payload.get("barcode") or "").strip() or None
    query = select(NutritionFood).where(NutritionFood.user_id == user_id)
    if barcode:
        query = query.where(NutritionFood.barcode == barcode)
    else:
        query = query.where(
            NutritionFood.name == (payload.get("name") or ""),
            NutritionFood.brand == (payload.get("brand") or ""),
            NutritionFood.source_provider == (payload.get("source_provider") or "manual"),
        )
    food = s.scalars(query.order_by(NutritionFood.user_corrected.desc())).first()
    if food is None:
        food = NutritionFood(
            user_id=user_id,
            name=str(payload.get("name") or "Food")[:300],
            brand=str(payload.get("brand") or "")[:200],
            barcode=barcode,
            source_provider=payload.get("source_provider") or "manual",
        )
        s.add(food)
    if not food.user_corrected:
        food.source_confidence = payload.get("source_confidence") or food.source_confidence
        if payload.get("serving_size") is not None:
            food.serving_size = float(payload["serving_size"])
        if payload.get("serving_unit"):
            food.serving_unit = str(payload["serving_unit"])[:60]
        for macro in _MACROS:
            key = f"{macro}_100g"
            if key in payload:
                setattr(food, key, _round1(payload[key]))
    s.flush()
    return food


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #
def log_food(
    user_id: int,
    *,
    name: str,
    meal_type: str,
    source: str,
    food_id: int | None = None,
    food_payload: dict | None = None,
    grams: float | None = None,
    servings: float | None = None,
    day: date | None = None,
    logged_at: datetime | None = None,
    notes: str = "",
) -> int:
    """Log one intake; returns the new FoodLog id.

    Either ``food_id`` (library row) or ``food_payload`` (a generics/OFF dict,
    upserted into the library first) links the log to a food; without both the
    log is a bare named entry. Portion: explicit ``grams`` wins, else
    ``servings`` x serving_size (default one serving, or 100 g when the food
    has no serving size).
    """
    logged_at = logged_at or datetime.now()
    day = day or logged_at.date()
    with session_scope() as s:
        food: NutritionFood | None = None
        if food_id is not None:
            food = s.get(NutritionFood, food_id)
            if food is None or food.user_id != user_id:
                raise ValueError(f"unknown food_id {food_id}")
        elif food_payload:
            food = _upsert_food(s, user_id, food_payload)

        if food is not None:
            if grams is None:
                servings = servings if servings is not None else 1.0
                grams = servings * (food.serving_size or 100.0)
            elif servings is None and food.serving_size:
                servings = round(grams / food.serving_size, 2)
            food.use_count = (food.use_count or 0) + 1
            food.last_used_at = utcnow()

        log = FoodLog(
            user_id=user_id,
            food_id=food.id if food is not None else None,
            name=(name or (food.name if food is not None else "Food"))[:300],
            meal_type=_meal_or_snack(meal_type),
            day=day,
            logged_at=logged_at,
            grams=grams,
            servings=servings,
            source=source,
            notes=notes or "",
        )
        if food is not None and grams:
            for macro in _MACROS:
                per100 = getattr(food, f"{macro}_100g")
                value = _round1(per100 * grams / 100.0) if per100 is not None else None
                setattr(log, macro, value)
        s.add(log)
        s.flush()
        return log.id


def quick_add(
    user_id: int,
    *,
    meal_type: str,
    calories: float,
    protein: float | None = None,
    carbs: float | None = None,
    fat: float | None = None,
    name: str = "Quick add",
) -> int:
    """Calorie-first entry for when weighing is not going to happen."""
    now = datetime.now()
    with session_scope() as s:
        log = FoodLog(
            user_id=user_id,
            name=name[:300],
            meal_type=_meal_or_snack(meal_type),
            day=now.date(),
            logged_at=now,
            calories=_round1(calories),
            protein=_round1(protein),
            carbs=_round1(carbs),
            fat=_round1(fat),
            source="quick",
        )
        s.add(log)
        s.flush()
        return log.id


def log_water(user_id: int, ml: float) -> int:
    """Water rides the FoodLog table (grams = ml) so one day query covers all."""
    now = datetime.now()
    with session_scope() as s:
        log = FoodLog(
            user_id=user_id,
            name="Water",
            meal_type="snack",
            day=now.date(),
            logged_at=now,
            grams=float(ml),
            calories=0.0,
            protein=0.0,
            carbs=0.0,
            fat=0.0,
            fibre=0.0,
            sugar=0.0,
            saturated_fat=0.0,
            sodium_mg=0.0,
            source="water",
        )
        s.add(log)
        s.flush()
        return log.id


def delete_log(user_id: int, log_id: int) -> bool:
    with session_scope() as s:
        log = s.get(FoodLog, log_id)
        if log is None or log.user_id != user_id:
            return False
        s.delete(log)
        return True


# --------------------------------------------------------------------------- #
# Day & week snapshots
# --------------------------------------------------------------------------- #
def _insights(
    *,
    totals: dict[str, float],
    targets: dict[str, float | None],
    water_ml: float,
    late_calories: float,
    logged_anything: bool,
    is_today: bool,
    now: datetime,
) -> list[str]:
    """Deterministic observations — calm statements, never guilt."""
    notes: list[str] = []
    protein_target, fibre_target = targets["protein"], targets["fibre"]
    if protein_target and totals["protein"] >= 0.9 * protein_target:
        notes.append("Protein is on track.")
        if fibre_target and totals["fibre"] < 0.6 * fibre_target:
            notes.append("Fibre is light — plants and grains close the gap.")
    calorie_target = targets["calories"]
    if calorie_target and totals["calories"] > calorie_target * 1.1:
        notes.append("Over target — one day, not a verdict. Tomorrow resets.")
    if totals["calories"] > 0 and late_calories / totals["calories"] > 0.4:
        notes.append("Most intake landed late today.")
    if is_today and not logged_anything and now.hour >= 14:
        notes.append("Nothing logged yet today.")
    water_target = targets["water_ml"]
    if is_today and now.hour >= 18 and water_target and water_ml < 0.5 * water_target:
        notes.append("Hydration is behind.")
    if totals["sodium_mg"] > 2300:
        notes.append("A salty day — worth knowing, not worrying.")
    return notes


def day_snapshot(user_id: int, day: date | None = None, *, now: datetime | None = None) -> dict:
    """Everything the Fuel page needs for one day, in one call.

    ``now`` exists for deterministic tests of the time-of-day insight rules;
    production callers leave it unset.
    """
    now = now or datetime.now()
    day = day or now.date()
    settings = settings_service.get_settings_snapshot(user_id)
    targets: dict[str, float | None] = {
        "calories": settings.get("calorie_target"),
        "protein": settings.get("protein_target_g"),
        "fibre": settings.get("fibre_target_g"),
        "water_ml": settings.get("water_target_ml"),
    }
    with session_scope() as s:
        logs = s.scalars(
            select(FoodLog)
            .where(FoodLog.user_id == user_id, FoodLog.day == day)
            .order_by(FoodLog.logged_at, FoodLog.id)
        ).all()
        food_logs = [log for log in logs if log.source != "water"]
        water_ml = round(sum(log.grams or 0 for log in logs if log.source == "water"))

        totals = {
            macro: round(sum(getattr(log, macro) or 0 for log in food_logs), 1)
            for macro in _MACROS
        }
        totals["water_ml"] = water_ml
        late_calories = sum(
            log.calories or 0 for log in food_logs if log.logged_at.hour >= 20
        )
        meals = []
        for meal_type in MEAL_TYPES:
            items = [
                {
                    "id": log.id,
                    "name": log.name,
                    "grams": log.grams,
                    "servings": log.servings,
                    "calories": log.calories,
                    "protein": log.protein,
                    "source": log.source,
                    "logged_at_label": log.logged_at.strftime("%H:%M"),
                }
                for log in food_logs
                if log.meal_type == meal_type
            ]
            meals.append({
                "meal_type": meal_type,
                "label": meal_type.capitalize(),
                "items": items,
                "calories": round(sum(item["calories"] or 0 for item in items), 1),
                "protein": round(sum(item["protein"] or 0 for item in items), 1),
            })
        timeline = [
            {
                "time_label": log.logged_at.strftime("%H:%M"),
                "name": log.name,
                "calories": log.calories,
                "meal_type": log.meal_type,
            }
            for log in food_logs
        ]

    remaining = {
        key: round(targets[key] - totals[key], 1) if targets[key] else None
        for key in ("calories", "protein", "fibre")
    }
    pct = {
        "calories": _pct(totals["calories"], targets["calories"]),
        "protein": _pct(totals["protein"], targets["protein"]),
        "fibre": _pct(totals["fibre"], targets["fibre"]),
        "water": _pct(water_ml, targets["water_ml"]),
    }
    logged_anything = bool(food_logs)
    return {
        "day": day,
        "totals": totals,
        "targets": targets,
        "remaining": remaining,
        "pct": pct,
        "meals": meals,
        "timeline": timeline,
        "insights": _insights(
            totals=totals,
            targets=targets,
            water_ml=water_ml,
            late_calories=late_calories,
            logged_anything=logged_anything,
            is_today=day == now.date(),
            now=now,
        ),
        "logged_anything": logged_anything,
        "water_ml": water_ml,
    }


def week_snapshot(user_id: int, days: int = 7) -> dict:
    """Rolling window ending today: series for charts plus consistency stats."""
    today = date.today()
    start = today - timedelta(days=days - 1)
    settings = settings_service.get_settings_snapshot(user_id)
    protein_target = settings.get("protein_target_g")
    fibre_target = settings.get("fibre_target_g")

    by_day: dict[date, list] = {}
    with session_scope() as s:
        logs = s.scalars(
            select(FoodLog).where(
                FoodLog.user_id == user_id,
                FoodLog.day >= start,
                FoodLog.day <= today,
                FoodLog.source != "water",
            )
        ).all()
        rows = [
            (log.day, log.name, log.calories or 0, log.protein or 0,
             log.fibre or 0, log.logged_at.hour)
            for log in logs
        ]
    for row in rows:
        by_day.setdefault(row[0], []).append(row)

    series = []
    protein_days = fibre_days = late_days = 0
    name_counter: Counter[str] = Counter()
    for offset in range(days):
        day = start + timedelta(days=offset)
        day_rows = by_day.get(day, [])
        calories = round(sum(r[2] for r in day_rows), 1)
        protein = round(sum(r[3] for r in day_rows), 1)
        fibre = round(sum(r[4] for r in day_rows), 1)
        series.append({"day": day.isoformat(), "calories": calories,
                       "protein": protein, "fibre": fibre})
        if day_rows:
            if protein_target and protein >= 0.9 * protein_target:
                protein_days += 1
            if fibre_target and fibre >= 0.9 * fibre_target:
                fibre_days += 1
            late = sum(r[2] for r in day_rows if r[5] >= 20)
            if calories > 0 and late / calories > 0.4:
                late_days += 1
            name_counter.update(r[1] for r in day_rows if r[1] not in ("Water", "Quick add"))

    days_logged = sum(1 for day_rows in by_day.values() if day_rows)
    logged_series = [point for point in series if by_day.get(date.fromisoformat(point["day"]))]
    averages = {
        key: round(sum(point[key] for point in logged_series) / days_logged, 1)
        if days_logged else 0.0
        for key in ("calories", "protein", "fibre")
    }
    return {
        "series": series,
        "averages": averages,
        "protein_consistency": int(round(100 * protein_days / days_logged)) if days_logged else 0,
        "fibre_consistency": int(round(100 * fibre_days / days_logged)) if days_logged else 0,
        "days_logged": days_logged,
        "top_foods": [{"name": name, "count": count}
                      for name, count in name_counter.most_common(5)],
        "late_eating_days": late_days,
    }


# --------------------------------------------------------------------------- #
# Search & library
# --------------------------------------------------------------------------- #
def search_local(user_id: int, q: str, limit: int = 12) -> list[dict]:
    """Library search: corrections first, then pinned, then most-used."""
    q = (q or "").strip()
    if not q:
        return []
    like = f"%{q}%"
    with session_scope() as s:
        rows = s.scalars(
            select(NutritionFood)
            .where(
                NutritionFood.user_id == user_id,
                or_(NutritionFood.name.ilike(like), NutritionFood.brand.ilike(like)),
            )
            .order_by(
                NutritionFood.user_corrected.desc(),
                NutritionFood.saved.desc(),
                NutritionFood.use_count.desc(),
                NutritionFood.name,
            )
            .limit(limit)
        ).all()
        return [_food_dict(food) for food in rows]


def search(user_id: int, q: str) -> dict:
    """Combined search: local library + generics always, OFF when enabled.

    OFF needs 3+ characters (its search is expensive and noisy below that) and
    only fills whatever headroom is left under a ~24-result total.
    """
    q = (q or "").strip()
    local = search_local(user_id, q, limit=12)
    generic = generics.search_generics(q, limit=8)
    off: list[dict] = []
    if len(q) >= 3 and settings_service.get_settings_snapshot(user_id).get("off_enabled"):
        headroom = max(0, 24 - len(local) - len(generic))
        if headroom:
            off = off_client.search_products(q, limit=min(12, headroom))
    return {"local": local, "generic": generic, "off": off}


def barcode_lookup(user_id: int, barcode: str) -> dict | None:
    """Local library first (a correction beats any provider), then OFF."""
    barcode = (barcode or "").strip()
    if not barcode:
        return None
    with session_scope() as s:
        food = s.scalars(
            select(NutritionFood)
            .where(NutritionFood.user_id == user_id, NutritionFood.barcode == barcode)
            .order_by(NutritionFood.user_corrected.desc(), NutritionFood.use_count.desc())
        ).first()
        if food is not None:
            return _food_dict(food)
    if settings_service.get_settings_snapshot(user_id).get("off_enabled"):
        return off_client.lookup_barcode(barcode)
    return None


def recent_foods(user_id: int, limit: int = 12) -> list[dict]:
    with session_scope() as s:
        rows = s.scalars(
            select(NutritionFood)
            .where(NutritionFood.user_id == user_id, NutritionFood.last_used_at.is_not(None))
            .order_by(NutritionFood.last_used_at.desc())
            .limit(limit)
        ).all()
        return [_food_dict(food) for food in rows]


def saved_foods(user_id: int) -> list[dict]:
    with session_scope() as s:
        rows = s.scalars(
            select(NutritionFood)
            .where(NutritionFood.user_id == user_id, NutritionFood.saved == 1)
            .order_by(NutritionFood.name)
        ).all()
        return [_food_dict(food) for food in rows]


def get_food(user_id: int, food_id: int) -> dict | None:
    with session_scope() as s:
        food = s.get(NutritionFood, food_id)
        if food is None or food.user_id != user_id:
            return None
        return _food_dict(food)


def toggle_saved(user_id: int, food_id: int) -> bool | None:
    """Pin/unpin a food; returns the new state, None when not found."""
    with session_scope() as s:
        food = s.get(NutritionFood, food_id)
        if food is None or food.user_id != user_id:
            return None
        food.saved = 0 if food.saved else 1
        return bool(food.saved)


def correct_food(user_id: int, food_id: int, fields: dict) -> dict | None:
    """Apply operator corrections; corrected rows outrank every provider."""
    with session_scope() as s:
        food = s.get(NutritionFood, food_id)
        if food is None or food.user_id != user_id:
            return None
        for key, raw in fields.items():
            if key in _CORRECTABLE_TEXT:
                value = str(raw or "").strip()
                if value:
                    setattr(food, key, value[:300])
            elif key in _CORRECTABLE_NUMBER:
                if raw is None or raw == "":
                    setattr(food, key, None)
                else:
                    try:
                        setattr(food, key, round(float(raw), 1))
                    except (TypeError, ValueError):
                        continue
        food.user_corrected = 1
        food.source_confidence = "high"
        return _food_dict(food)


# --------------------------------------------------------------------------- #
# Repeats & templates
# --------------------------------------------------------------------------- #
def _copy_logs(user_id: int, from_day: date, to_day: date, meal_type: str | None = None) -> int:
    """Re-log a past day/meal as-is (macro snapshots copied, water excluded)."""
    now = datetime.now()
    with session_scope() as s:
        query = select(FoodLog).where(
            FoodLog.user_id == user_id,
            FoodLog.day == from_day,
            FoodLog.source != "water",
        )
        if meal_type is not None:
            query = query.where(FoodLog.meal_type == meal_type)
        rows = s.scalars(query.order_by(FoodLog.logged_at, FoodLog.id)).all()
        for row in rows:
            s.add(FoodLog(
                user_id=user_id,
                food_id=row.food_id,
                name=row.name,
                meal_type=row.meal_type,
                day=to_day,
                logged_at=now,
                grams=row.grams,
                servings=row.servings,
                source="repeat",
                notes=row.notes,
                **{macro: getattr(row, macro) for macro in _MACROS},
            ))
            if row.food_id is not None:
                food = s.get(NutritionFood, row.food_id)
                if food is not None:
                    food.use_count = (food.use_count or 0) + 1
                    food.last_used_at = utcnow()
        return len(rows)


def repeat_yesterday(user_id: int) -> int:
    today = date.today()
    return _copy_logs(user_id, today - timedelta(days=1), today)


def repeat_meal(user_id: int, from_day: date, meal_type: str) -> int:
    return _copy_logs(user_id, from_day, date.today(), meal_type)


def create_template_from_meal(user_id: int, day: date, meal_type: str, name: str) -> int | None:
    """Freeze a logged meal into a reusable template; None when meal is empty.

    Only food-linked logs are kept: quick adds and water carry no per-100g
    source, so they cannot be re-priced when the template is applied later.
    """
    with session_scope() as s:
        rows = s.scalars(
            select(FoodLog)
            .where(
                FoodLog.user_id == user_id,
                FoodLog.day == day,
                FoodLog.meal_type == meal_type,
                FoodLog.food_id.is_not(None),
            )
            .order_by(FoodLog.logged_at, FoodLog.id)
        ).all()
        items = [
            {"food_id": row.food_id, "name": row.name,
             "grams": row.grams, "servings": row.servings}
            for row in rows
        ]
        if not items:
            return None
        template = MealTemplate(
            user_id=user_id,
            name=(name or f"{meal_type.capitalize()} {day.isoformat()}")[:200],
            items=items,
        )
        s.add(template)
        s.flush()
        return template.id


def list_templates(user_id: int) -> list[dict]:
    """Templates with live totals — computed from current per-100g values."""
    with session_scope() as s:
        templates = s.scalars(
            select(MealTemplate)
            .where(MealTemplate.user_id == user_id)
            .order_by(MealTemplate.created_at.desc())
        ).all()
        out = []
        for template in templates:
            items = list(template.items or [])
            calories = protein = 0.0
            for item in items:
                food = s.get(NutritionFood, item["food_id"]) if item.get("food_id") else None
                if food is None:
                    continue
                grams = item.get("grams") or (item.get("servings") or 1) * (
                    food.serving_size or 100.0
                )
                calories += (food.calories_100g or 0) * grams / 100.0
                protein += (food.protein_100g or 0) * grams / 100.0
            out.append({
                "id": template.id,
                "name": template.name,
                "items": items,
                "item_count": len(items),
                "calories": round(calories, 1),
                "protein": round(protein, 1),
                "last_used_at": (
                    template.last_used_at.isoformat() if template.last_used_at else None
                ),
            })
        return out


def apply_template(user_id: int, template_id: int, meal_type: str | None = None) -> int:
    """Log a template's items today; returns how many were logged."""
    with session_scope() as s:
        template = s.get(MealTemplate, template_id)
        if template is None or template.user_id != user_id:
            return 0
        items = list(template.items or [])
        template.last_used_at = utcnow()
    meal = meal_type if meal_type in MEAL_TYPES else _meal_for_hour(datetime.now().hour)
    count = 0
    for item in items:
        if not item.get("food_id"):
            continue
        try:
            log_food(
                user_id,
                name=item.get("name") or "",
                meal_type=meal,
                source="repeat",
                food_id=item["food_id"],
                grams=item.get("grams"),
                servings=item.get("servings"),
            )
            count += 1
        except ValueError:
            continue  # food deleted since the template was made — skip, don't fail
    return count
