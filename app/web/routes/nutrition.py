"""Nutrition (Fuel): logging, search, barcode, templates, daily/weekly readouts.

Zero-subscription by design: local foods first, Open Food Facts for barcodes
and packaged search, UK generic references for whole foods, manual entry
always available. Corrections stay local and win future lookups.
"""

from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.domains.nutrition import service as nutrition
from app.web.context import apply_client_mutation, page, user_id, write_response

router = APIRouter()


def _parse_day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return date.today()


@router.get("/nutrition", response_class=HTMLResponse)
def nutrition_page(request: Request, day: str = "", saved: str = ""):
    uid = user_id()
    view_day = _parse_day(day) if day else date.today()
    return page(
        request,
        "nutrition.html",
        "nutrition",
        snap=nutrition.day_snapshot(uid, view_day),
        week=nutrition.week_snapshot(uid),
        view_day=view_day,
        is_today=view_day == date.today(),
        prev_day=(view_day.fromordinal(view_day.toordinal() - 1)),
        next_day=(view_day.fromordinal(view_day.toordinal() + 1)),
        recent=nutrition.recent_foods(uid, limit=8),
        saved_foods=nutrition.saved_foods(uid),
        templates=nutrition.list_templates(uid),
        meal_types=nutrition.MEAL_TYPES,
        saved_note={"logged": "Logged.", "water": "Water logged.",
                    "repeat": "Copied.", "template": "Template applied.",
                    "corrected": "Correction saved — it wins future lookups."}
                   .get(saved, ""),
    )


@router.get("/nutrition/scan", response_class=HTMLResponse)
def nutrition_scan(request: Request):
    return page(request, "nutrition_scan.html", "nutrition",
                meal_types=nutrition.MEAL_TYPES)


@router.post("/nutrition/log")
def nutrition_log(
    request: Request,
    name: str = Form(""),
    meal_type: str = Form("snack"),
    source: str = Form("search"),
    food_id: str = Form(""),
    food_payload: str = Form(""),
    grams: str = Form(""),
    servings: str = Form(""),
    day: str = Form(""),
    client_mutation_id: str = Form(""),
):
    uid = user_id()
    payload = None
    if food_payload.strip():
        try:
            payload = json.loads(food_payload)
        except json.JSONDecodeError:
            payload = None

    def apply():
        log_id = nutrition.log_food(
            uid,
            name=name,
            meal_type=meal_type,
            source=source,
            food_id=int(food_id) if food_id.strip() else None,
            food_payload=payload if isinstance(payload, dict) else None,
            grams=float(grams) if grams.strip() else None,
            servings=float(servings) if servings.strip() else None,
            day=_parse_day(day) if day.strip() else None,
        )
        return {"record_id": log_id}

    result = apply_client_mutation(uid, client_mutation_id, "nutrition.log", apply)
    return write_response(request, "/nutrition?saved=logged", result)


@router.post("/nutrition/quick")
def nutrition_quick(
    request: Request,
    meal_type: str = Form("snack"),
    calories: str = Form(""),
    protein: str = Form(""),
    name: str = Form(""),
    client_mutation_id: str = Form(""),
):
    uid = user_id()

    def apply():
        log_id = nutrition.quick_add(
            uid,
            meal_type=meal_type,
            calories=float(calories) if calories.strip() else 0.0,
            protein=float(protein) if protein.strip() else None,
            name=name.strip() or "Quick add",
        )
        return {"record_id": log_id}

    result = apply_client_mutation(uid, client_mutation_id, "nutrition.quick", apply)
    return write_response(request, "/nutrition?saved=logged", result)


@router.post("/nutrition/water")
def nutrition_water(request: Request, ml: str = Form("250"),
                    client_mutation_id: str = Form("")):
    uid = user_id()

    def apply():
        log_id = nutrition.log_water(uid, float(ml) if ml.strip() else 250.0)
        return {"record_id": log_id}

    result = apply_client_mutation(uid, client_mutation_id, "nutrition.water", apply)
    return write_response(request, "/nutrition?saved=water", result)


@router.post("/nutrition/logs/{log_id}/delete")
def nutrition_delete(log_id: int):
    nutrition.delete_log(user_id(), log_id)
    return RedirectResponse("/nutrition", status_code=303)


@router.post("/nutrition/repeat-yesterday")
def nutrition_repeat_yesterday():
    nutrition.repeat_yesterday(user_id())
    return RedirectResponse("/nutrition?saved=repeat", status_code=303)


@router.post("/nutrition/repeat-meal")
def nutrition_repeat_meal(from_day: str = Form(""), meal_type: str = Form("lunch")):
    nutrition.repeat_meal(user_id(), _parse_day(from_day), meal_type)
    return RedirectResponse("/nutrition?saved=repeat", status_code=303)


@router.post("/nutrition/templates/from-meal")
def nutrition_template_from_meal(
    day: str = Form(""), meal_type: str = Form("lunch"), name: str = Form("")
):
    nutrition.create_template_from_meal(
        user_id(), _parse_day(day), meal_type, name.strip() or f"Saved {meal_type}"
    )
    return RedirectResponse("/nutrition", status_code=303)


@router.post("/nutrition/templates/{template_id}/apply")
def nutrition_template_apply(template_id: int, meal_type: str = Form("")):
    nutrition.apply_template(user_id(), template_id,
                             meal_type=meal_type.strip() or None)
    return RedirectResponse("/nutrition?saved=template", status_code=303)


@router.post("/nutrition/foods/{food_id}/save")
def nutrition_food_save(food_id: int):
    nutrition.toggle_saved(user_id(), food_id)
    return RedirectResponse("/nutrition", status_code=303)


@router.post("/nutrition/foods/{food_id}/correct")
def nutrition_food_correct(
    food_id: int,
    name: str = Form(""),
    calories_100g: str = Form(""),
    protein_100g: str = Form(""),
    carbs_100g: str = Form(""),
    fat_100g: str = Form(""),
    fibre_100g: str = Form(""),
    serving_size: str = Form(""),
):
    fields: dict = {}
    if name.strip():
        fields["name"] = name.strip()
    for key, raw in (
        ("calories_100g", calories_100g), ("protein_100g", protein_100g),
        ("carbs_100g", carbs_100g), ("fat_100g", fat_100g),
        ("fibre_100g", fibre_100g), ("serving_size", serving_size),
    ):
        if raw.strip():
            try:
                fields[key] = float(raw)
            except ValueError:
                pass
    if fields:
        nutrition.correct_food(user_id(), food_id, fields)
    return RedirectResponse("/nutrition?saved=corrected", status_code=303)
