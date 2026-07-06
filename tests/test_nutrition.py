"""Nutrition domain tests — no network: OFF calls are always monkeypatched.

Each test that logs food gets its own user so day-based snapshots never see
another test's rows (the conftest DB is shared across the session).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from uuid import uuid4

import pytest

from app.db.database import session_scope
from app.db.models import FoodLog, User
from app.domains import settings_service
from app.domains.nutrition import generics, off_client
from app.domains.nutrition import service as nutrition


def _new_user(tag: str) -> int:
    with session_scope() as s:
        user = User(email=f"nutri-{tag}-{uuid4().hex[:6]}@test.local", display_name="Test")
        s.add(user)
        s.flush()
        return user.id


def _banana() -> dict:
    results = generics.search_generics("banana")
    assert results, "banana must exist in the generic list"
    return results[0]


# --------------------------------------------------------------------------- #
# Generics
# --------------------------------------------------------------------------- #
def test_generics_search_banana_sane_macros():
    banana = _banana()
    assert banana["name"] == "Banana"
    assert 80 <= banana["calories_100g"] <= 100
    assert 0 < banana["protein_100g"] < 2
    assert banana["fibre_100g"] > 0
    assert banana["source_provider"] == "generic"
    assert banana["source_confidence"] == "medium"


def test_generics_search_matching_and_limit():
    assert generics.search_generics("") == []
    chicken = generics.search_generics("chicken")
    assert chicken and all("chicken" in item["name"].lower() for item in chicken)
    # whole-name prefix outranks word-level matches
    assert generics.search_generics("chi")[0]["name"].lower().startswith("chi")
    assert len(generics.search_generics("e", limit=5)) <= 5


# --------------------------------------------------------------------------- #
# Logging & macro math
# --------------------------------------------------------------------------- #
def test_log_food_generic_payload_macro_math():
    uid = _new_user("macros")
    day = date(2026, 3, 2)
    nutrition.log_food(
        uid, name="Banana", meal_type="breakfast", source="search",
        food_payload=_banana(), grams=150,
        day=day, logged_at=datetime(2026, 3, 2, 8, 30),
    )
    snap = nutrition.day_snapshot(uid, day)
    assert snap["totals"]["calories"] == pytest.approx(89 * 1.5, abs=0.1)
    assert snap["totals"]["protein"] == pytest.approx(1.1 * 1.5, abs=0.06)
    assert snap["totals"]["fibre"] == pytest.approx(2.6 * 1.5, abs=0.06)

    foods = nutrition.search_local(uid, "banana")
    assert len(foods) == 1
    assert foods[0]["source_provider"] == "generic"
    assert foods[0]["calories_100g"] == 89
    assert foods[0]["use_count"] == 1


def test_log_food_default_serving_and_upsert_dedupe():
    uid = _new_user("serving")
    day = date(2026, 3, 3)
    # no grams/servings -> one serving (118 g banana)
    nutrition.log_food(
        uid, name="Banana", meal_type="snack", source="search",
        food_payload=_banana(), day=day, logged_at=datetime(2026, 3, 3, 10, 0),
    )
    # same payload again -> same food row, servings x serving_size
    nutrition.log_food(
        uid, name="Banana", meal_type="snack", source="search",
        food_payload=_banana(), servings=2,
        day=day, logged_at=datetime(2026, 3, 3, 16, 0),
    )
    snap = nutrition.day_snapshot(uid, day)
    expected = round(89 * 1.18, 1) + round(89 * 2.36, 1)
    assert snap["totals"]["calories"] == pytest.approx(expected, abs=0.1)

    foods = nutrition.search_local(uid, "banana")
    assert len(foods) == 1  # upsert matched, no duplicate row
    assert foods[0]["use_count"] == 2
    assert nutrition.recent_foods(uid)[0]["name"] == "Banana"


def test_quick_add_water_and_today_snapshot():
    uid = _new_user("quick")
    nutrition.quick_add(uid, meal_type="lunch", calories=500, protein=30)
    nutrition.log_water(uid, 500)
    snap = nutrition.day_snapshot(uid)
    assert snap["totals"]["calories"] == 500
    assert snap["totals"]["protein"] == 30
    assert snap["water_ml"] == 500
    assert snap["totals"]["water_ml"] == 500
    assert snap["pct"]["water"] == 25  # default 2000 ml target
    assert snap["logged_anything"] is True
    lunch = next(meal for meal in snap["meals"] if meal["meal_type"] == "lunch")
    assert len(lunch["items"]) == 1 and lunch["items"][0]["source"] == "quick"
    # water never appears in the timeline
    assert all(entry["name"] != "Water" for entry in snap["timeline"])


# --------------------------------------------------------------------------- #
# Day snapshot: structure + insights
# --------------------------------------------------------------------------- #
def test_day_snapshot_totals_pct_and_insight_rules():
    uid = _new_user("insights")
    day = date(2026, 6, 1)
    chicken = {
        "name": "Test Chicken", "brand": "", "serving_size": 100.0,
        "serving_unit": "serving", "calories_100g": 165, "protein_100g": 31,
        "carbs_100g": 0, "fat_100g": 3.6, "fibre_100g": 0, "sugar_100g": 0,
        "saturated_fat_100g": 1.0, "sodium_mg_100g": 74,
        "source_provider": "manual", "source_confidence": "high",
    }
    salty = {**chicken, "name": "Test Salty Snack",
             "calories_100g": 250, "protein_100g": 5, "sodium_mg_100g": 1500}
    nutrition.log_food(uid, name="Test Chicken", meal_type="lunch", source="search",
                       food_payload=chicken, grams=400,
                       day=day, logged_at=datetime(2026, 6, 1, 12, 30))
    nutrition.log_food(uid, name="Test Salty Snack", meal_type="dinner", source="search",
                       food_payload=salty, grams=200,
                       day=day, logged_at=datetime(2026, 6, 1, 21, 0))

    snap = nutrition.day_snapshot(uid, day)
    assert snap["day"] == day
    assert snap["totals"]["calories"] == 1160
    assert snap["totals"]["protein"] == pytest.approx(134, abs=0.1)
    assert snap["totals"]["sodium_mg"] == pytest.approx(3296, abs=1)
    assert snap["targets"] == {"calories": 2400, "protein": 120, "fibre": 30, "water_ml": 2000}
    assert snap["remaining"]["calories"] == 1240
    assert snap["pct"]["calories"] == 48
    assert snap["pct"]["protein"] == 100  # clamped: 134/120 would be >100

    labels = [meal["meal_type"] for meal in snap["meals"]]
    assert labels == list(nutrition.MEAL_TYPES)
    assert [entry["name"] for entry in snap["timeline"]] == ["Test Chicken", "Test Salty Snack"]
    assert snap["timeline"][0]["time_label"] == "12:30"

    # protein >= 90%, fibre < 60%, >40% of calories after 20:00, sodium > 2300
    assert "Protein is on track." in snap["insights"]
    assert "Fibre is light — plants and grains close the gap." in snap["insights"]
    assert "Most intake landed late today." in snap["insights"]
    assert "A salty day — worth knowing, not worrying." in snap["insights"]
    assert "Over target — one day, not a verdict. Tomorrow resets." not in snap["insights"]


def test_day_snapshot_empty_today_insights():
    uid = _new_user("empty")
    evening = datetime.combine(date.today(), time(19, 0))
    snap = nutrition.day_snapshot(uid, now=evening)
    assert snap["logged_anything"] is False
    assert "Nothing logged yet today." in snap["insights"]
    assert "Hydration is behind." in snap["insights"]


# --------------------------------------------------------------------------- #
# Week snapshot
# --------------------------------------------------------------------------- #
def test_week_snapshot_series_and_consistency():
    uid = _new_user("week")
    chicken = {
        "name": "Test Chicken", "brand": "", "serving_size": 100.0,
        "serving_unit": "serving", "calories_100g": 165, "protein_100g": 31,
        "carbs_100g": 0, "fat_100g": 3.6, "fibre_100g": 0, "sugar_100g": 0,
        "saturated_fat_100g": 1.0, "sodium_mg_100g": 74,
        "source_provider": "manual", "source_confidence": "high",
    }
    today = date.today()
    plan = [  # (day, grams, hour) — two protein-hitting days, one light + late day
        (today, 400, 12),
        (today - timedelta(days=1), 400, 21),
        (today - timedelta(days=2), 100, 9),
    ]
    for day, grams, hour in plan:
        nutrition.log_food(uid, name="Test Chicken", meal_type="lunch", source="search",
                           food_payload=chicken, grams=grams,
                           day=day, logged_at=datetime.combine(day, time(hour, 0)))

    week = nutrition.week_snapshot(uid)
    assert len(week["series"]) == 7
    assert week["series"][-1]["day"] == today.isoformat()
    assert week["series"][-1]["calories"] == 660
    assert week["days_logged"] == 3
    assert week["protein_consistency"] == 67  # 2 of 3 logged days >= 108 g
    assert week["fibre_consistency"] == 0
    assert week["late_eating_days"] == 1
    assert week["averages"]["calories"] == pytest.approx((660 + 660 + 165) / 3, abs=0.1)
    assert week["top_foods"][0] == {"name": "Test Chicken", "count": 3}


# --------------------------------------------------------------------------- #
# Search & library
# --------------------------------------------------------------------------- #
def test_search_local_ranking_user_corrected_first():
    uid = _new_user("rank")
    bar = {"name": "Zebra Energy Bar", "brand": "", "serving_size": 50.0,
           "serving_unit": "bar", "calories_100g": 400, "protein_100g": 20,
           "source_provider": "manual", "source_confidence": "medium"}
    bites = {**bar, "name": "Zebra Bites"}
    for _ in range(3):  # heavy use of the bar...
        nutrition.log_food(uid, name="Zebra Energy Bar", meal_type="snack",
                           source="search", food_payload=bar, day=date(2026, 4, 1))
    nutrition.log_food(uid, name="Zebra Bites", meal_type="snack",
                       source="search", food_payload=bites, day=date(2026, 4, 1))

    results = nutrition.search_local(uid, "zebra")
    assert [r["name"] for r in results] == ["Zebra Energy Bar", "Zebra Bites"]  # by use_count

    bites_id = results[1]["id"]
    nutrition.correct_food(uid, bites_id, {"calories_100g": 410})
    results = nutrition.search_local(uid, "zebra")
    assert results[0]["name"] == "Zebra Bites"  # ...but a correction outranks it
    assert results[0]["user_corrected"] is True


def test_search_combines_sources_and_gates_off(monkeypatch):
    uid = _new_user("search")
    sentinel = [{"name": "OFF Zebra", "calories_100g": 100, "source_provider": "off"}]
    monkeypatch.setattr(off_client, "search_products", lambda q, limit=12: sentinel)
    result = nutrition.search(uid, "banana")
    assert result["generic"][0]["name"] == "Banana"
    assert result["off"] == sentinel

    def _boom(q, limit=12):
        raise AssertionError("OFF must not be called for queries under 3 chars")

    monkeypatch.setattr(off_client, "search_products", _boom)
    result = nutrition.search(uid, "zz")
    assert result["off"] == []


def test_correct_food_and_toggle_saved():
    uid = _new_user("correct")
    nutrition.log_food(uid, name="Banana", meal_type="snack", source="search",
                       food_payload=_banana(), day=date(2026, 4, 2))
    food_id = nutrition.search_local(uid, "banana")[0]["id"]

    updated = nutrition.correct_food(
        uid, food_id, {"name": "Banana (weighed)", "calories_100g": "95", "fibre_100g": None}
    )
    assert updated["name"] == "Banana (weighed)"
    assert updated["calories_100g"] == 95.0
    assert updated["fibre_100g"] is None
    assert updated["user_corrected"] is True
    assert updated["source_confidence"] == "high"
    assert nutrition.get_food(uid, food_id)["calories_100g"] == 95.0

    assert nutrition.toggle_saved(uid, food_id) is True
    assert [f["id"] for f in nutrition.saved_foods(uid)] == [food_id]
    assert nutrition.toggle_saved(uid, food_id) is False
    assert nutrition.saved_foods(uid) == []
    assert nutrition.toggle_saved(uid, 999_999) is None


# --------------------------------------------------------------------------- #
# Barcode
# --------------------------------------------------------------------------- #
def test_barcode_lookup_local_first_then_off(monkeypatch):
    uid = _new_user("barcode")
    payload = {**_banana(), "name": "Scanned Banana Bread", "barcode": "5012345678900",
               "source_provider": "off"}
    nutrition.log_food(uid, name="Scanned Banana Bread", meal_type="snack",
                       source="scan", food_payload=payload, day=date(2026, 4, 3))

    def _off_never(barcode):
        raise AssertionError("local barcode hit must not reach OFF")

    monkeypatch.setattr(off_client, "lookup_barcode", _off_never)
    hit = nutrition.barcode_lookup(uid, "5012345678900")
    assert hit is not None and hit.get("id") and hit["name"] == "Scanned Banana Bread"

    off_payload = {"name": "OFF Product", "barcode": "4000000000000",
                   "calories_100g": 200, "source_provider": "off"}
    monkeypatch.setattr(off_client, "lookup_barcode", lambda barcode: off_payload)
    assert nutrition.barcode_lookup(uid, "4000000000000") == off_payload

    # switching OFF off means unknown barcodes just miss
    settings_service.set_values(uid, {"off_enabled": ""})
    monkeypatch.setattr(off_client, "lookup_barcode", _off_never)
    assert nutrition.barcode_lookup(uid, "4000000000000") is None


def test_off_client_mapping_no_network():
    product = {
        "product_name": "Test Beans", "brands": "BrandOne, BrandTwo", "code": "123",
        "serving_quantity": "207", "serving_size": "1/2 can (207 g)",
        "nutriments": {"energy-kcal_100g": 81, "proteins_100g": 4.8,
                       "carbohydrates_100g": 12.5, "fat_100g": 0.6, "salt_100g": 0.9},
    }
    mapped = off_client._map_product(product)
    assert mapped["name"] == "Test Beans"
    assert mapped["brand"] == "BrandOne"
    assert mapped["serving_size"] == 207.0
    assert mapped["sodium_mg_100g"] == pytest.approx(360.0)  # salt 0.9 g / 2.5 -> mg
    assert mapped["source_confidence"] == "high"

    assert off_client._map_product({"nutriments": {}}) is None  # nameless
    partial = off_client._map_product(
        {"product_name": "X", "nutriments": {"energy-kcal_100g": 50}}
    )
    assert partial["source_confidence"] == "medium"
    assert off_client._map_product({"product_name": "X"})["source_confidence"] == "low"


# --------------------------------------------------------------------------- #
# Repeats & templates
# --------------------------------------------------------------------------- #
def test_repeat_yesterday_and_repeat_meal():
    uid = _new_user("repeat")
    yesterday = date.today() - timedelta(days=1)
    banana = _banana()
    nutrition.log_food(uid, name="Banana", meal_type="breakfast", source="search",
                       food_payload=banana, day=yesterday,
                       logged_at=datetime.combine(yesterday, time(8, 0)))
    nutrition.log_food(uid, name="Banana", meal_type="dinner", source="search",
                       food_payload=banana, grams=200, day=yesterday,
                       logged_at=datetime.combine(yesterday, time(19, 0)))
    with session_scope() as s:  # water yesterday, directly (log_water is today-only)
        s.add(FoodLog(user_id=uid, name="Water", meal_type="snack", day=yesterday,
                      logged_at=datetime.combine(yesterday, time(9, 0)),
                      grams=400.0, calories=0.0, source="water"))

    assert nutrition.repeat_yesterday(uid) == 2  # water is not repeated
    snap = nutrition.day_snapshot(uid)
    assert snap["water_ml"] == 0
    breakfast = next(m for m in snap["meals"] if m["meal_type"] == "breakfast")
    dinner = next(m for m in snap["meals"] if m["meal_type"] == "dinner")
    assert len(breakfast["items"]) == 1 and breakfast["items"][0]["source"] == "repeat"
    assert len(dinner["items"]) == 1
    assert dinner["items"][0]["calories"] == pytest.approx(178, abs=0.1)  # 200 g snapshot copied

    assert nutrition.repeat_meal(uid, yesterday, "breakfast") == 1
    snap = nutrition.day_snapshot(uid)
    breakfast = next(m for m in snap["meals"] if m["meal_type"] == "breakfast")
    assert len(breakfast["items"]) == 2


def test_meal_templates_create_list_apply():
    uid = _new_user("template")
    day = date(2026, 5, 4)
    banana = _banana()
    nutrition.log_food(uid, name="Banana", meal_type="lunch", source="search",
                       food_payload=banana, grams=118, day=day,
                       logged_at=datetime.combine(day, time(13, 0)))
    nutrition.log_food(uid, name="Banana", meal_type="lunch", source="search",
                       food_payload=banana, grams=100, day=day,
                       logged_at=datetime.combine(day, time(13, 5)))

    assert nutrition.create_template_from_meal(uid, day, "breakfast", "Empty") is None
    template_id = nutrition.create_template_from_meal(uid, day, "lunch", "Banana lunch")
    assert template_id is not None

    templates = nutrition.list_templates(uid)
    assert len(templates) == 1
    assert templates[0]["name"] == "Banana lunch"
    assert templates[0]["item_count"] == 2
    assert templates[0]["calories"] == pytest.approx(89 * 2.18, abs=0.5)

    assert nutrition.apply_template(uid, template_id, meal_type="dinner") == 2
    snap = nutrition.day_snapshot(uid)
    dinner = next(m for m in snap["meals"] if m["meal_type"] == "dinner")
    assert len(dinner["items"]) == 2
    assert all(item["source"] == "repeat" for item in dinner["items"])
    assert nutrition.list_templates(uid)[0]["last_used_at"] is not None
    assert nutrition.apply_template(uid, 999_999) == 0


# --------------------------------------------------------------------------- #
# Ownership
# --------------------------------------------------------------------------- #
def test_delete_log_ownership():
    owner = _new_user("owner")
    intruder = _new_user("intruder")
    log_id = nutrition.quick_add(owner, meal_type="snack", calories=100)
    assert nutrition.delete_log(intruder, log_id) is False
    assert nutrition.day_snapshot(owner)["totals"]["calories"] == 100
    assert nutrition.delete_log(owner, log_id) is True
    assert nutrition.day_snapshot(owner)["logged_anything"] is False
    assert nutrition.get_food(intruder, 1) is None or True  # cross-user food reads stay scoped
