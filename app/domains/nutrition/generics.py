"""Curated UK generic reference foods.

These are generic reference estimates (McCance & Widdowson-style published
values) for everyday UK staples, provided so a meal can be logged in seconds
without a barcode. They are convenience numbers, deliberately marked
``source_confidence="medium"``: a scanned or user-corrected product is always
more trustworthy than a generic entry, and lookups rank accordingly.

All macro values are per 100 g; ``serving_size`` is the grams of one typical
portion described by ``serving_unit``.
"""

from __future__ import annotations

_FIELDS = (
    "name", "serving_size", "serving_unit", "calories_100g", "protein_100g",
    "carbs_100g", "fat_100g", "fibre_100g", "sugar_100g", "saturated_fat_100g",
    "sodium_mg_100g",
)

# (name, portion g, portion label, kcal, protein, carbs, fat, fibre, sugar, sat fat, sodium mg)
_ROWS: tuple[tuple, ...] = (
    # -- fruit
    ("Banana", 118, "medium banana", 89, 1.1, 22.8, 0.3, 2.6, 12.2, 0.1, 1),
    ("Apple", 182, "medium apple", 52, 0.3, 13.8, 0.2, 2.4, 10.4, 0.0, 1),
    ("Orange", 130, "medium orange", 47, 0.9, 11.8, 0.1, 2.4, 9.4, 0.0, 0),
    ("Grapes", 80, "handful", 69, 0.7, 18.1, 0.2, 0.9, 15.5, 0.1, 2),
    ("Strawberries", 100, "handful", 32, 0.7, 7.7, 0.3, 2.0, 4.9, 0.0, 1),
    ("Blueberries", 80, "handful", 57, 0.7, 14.5, 0.3, 2.4, 10.0, 0.0, 1),
    ("Avocado", 75, "half avocado", 160, 2.0, 8.5, 14.7, 6.7, 0.7, 2.1, 7),
    # -- vegetables & sides
    ("Tomato", 85, "medium tomato", 18, 0.9, 3.9, 0.2, 1.2, 2.6, 0.0, 5),
    ("Cucumber", 50, "5 cm piece", 12, 0.7, 2.2, 0.1, 0.7, 1.7, 0.0, 2),
    ("Broccoli (boiled)", 85, "serving", 28, 3.0, 2.8, 0.4, 2.6, 1.5, 0.1, 8),
    ("Spinach (boiled)", 90, "serving", 23, 2.9, 0.8, 0.5, 2.1, 0.4, 0.1, 120),
    ("Peas (boiled)", 80, "serving", 79, 6.0, 9.7, 0.9, 5.1, 2.3, 0.2, 1),
    ("Carrots (boiled)", 80, "serving", 27, 0.6, 5.6, 0.4, 2.7, 4.4, 0.1, 35),
    ("Onion (raw)", 80, "half onion", 40, 1.1, 9.3, 0.1, 1.7, 4.2, 0.0, 4),
    ("Sweet potato (baked)", 150, "medium sweet potato", 90, 2.0, 20.7, 0.2, 3.3, 6.5, 0.1, 36),
    ("Potato (boiled)", 180, "medium potato", 72, 1.8, 17.0, 0.1, 1.6, 0.7, 0.0, 7),
    ("Jacket potato (baked, skin on)", 180, "medium jacket", 93, 2.5, 21.1, 0.1, 2.6, 1.2, 0.0, 6),
    ("Mashed potato (milk and butter)", 180, "serving", 104, 1.8, 15.5, 4.3, 1.4, 0.7, 2.4, 250),
    ("Oven chips (baked)", 165, "serving", 162, 2.6, 26.4, 5.3, 2.5, 0.6, 0.7, 55),
    # -- grains, bread & cereal
    ("Porridge oats (dry)", 40, "serving (dry)", 379, 13.2, 67.7, 6.5, 10.1, 1.0, 1.2, 6),
    ("Porridge (semi-skimmed milk)", 250, "bowl", 102, 4.3, 15.5, 2.4, 1.5, 5.5, 1.2, 45),
    ("White rice (cooked)", 180, "serving", 130, 2.7, 28.2, 0.3, 0.4, 0.1, 0.1, 1),
    ("Brown rice (cooked)", 180, "serving", 112, 2.6, 23.5, 0.9, 1.8, 0.4, 0.2, 4),
    ("Pasta (cooked)", 180, "serving", 158, 5.8, 30.9, 0.9, 1.8, 0.6, 0.2, 1),
    ("Wholemeal pasta (cooked)", 180, "serving", 149, 6.3, 28.7, 1.1, 3.9, 0.8, 0.2, 3),
    ("White bread", 36, "medium slice", 236, 8.6, 44.0, 1.7, 2.5, 3.3, 0.4, 400),
    ("Wholemeal bread", 36, "medium slice", 218, 9.4, 36.0, 2.5, 6.5, 2.8, 0.5, 380),
    ("Bagel (plain)", 85, "bagel", 256, 10.0, 49.0, 1.6, 2.7, 6.6, 0.4, 430),
    ("Tortilla wrap", 62, "wrap", 300, 8.2, 50.0, 7.0, 2.9, 3.0, 3.0, 570),
    ("Cornflakes", 30, "bowl", 378, 7.0, 84.0, 0.9, 3.0, 8.0, 0.2, 730),
    ("Granola", 45, "serving", 448, 9.5, 62.0, 17.0, 6.5, 18.0, 4.5, 20),
    ("Muesli", 45, "serving", 362, 9.8, 66.0, 5.9, 7.6, 16.0, 1.0, 30),
    # -- dairy & eggs
    ("Whole milk", 200, "glass", 64, 3.3, 4.7, 3.7, 0.0, 4.7, 2.3, 43),
    ("Semi-skimmed milk", 200, "glass", 47, 3.5, 4.8, 1.7, 0.0, 4.8, 1.1, 43),
    ("Skimmed milk", 200, "glass", 34, 3.4, 4.9, 0.2, 0.0, 4.9, 0.1, 44),
    ("Greek yogurt (full fat)", 150, "pot", 97, 9.0, 3.9, 5.0, 0.0, 3.9, 3.5, 35),
    ("Greek yogurt (0% fat)", 150, "pot", 57, 10.3, 3.6, 0.2, 0.0, 3.2, 0.1, 36),
    ("Cheddar cheese", 30, "matchbox-sized piece", 416, 25.4, 0.1, 34.9, 0.0, 0.1, 21.7, 700),
    ("Butter", 7, "thin spread", 744, 0.6, 0.6, 82.2, 0.0, 0.6, 52.1, 600),
    ("Egg (boiled)", 58, "medium egg", 143, 12.6, 0.7, 9.9, 0.0, 0.7, 3.1, 140),
    # -- meat & fish
    ("Chicken breast (grilled)", 150, "breast fillet", 165, 31.0, 0.0, 3.6, 0.0, 0.0, 1.0, 74),
    ("Chicken thigh (roasted, skinless)", 100, "thigh", 209, 26.0, 0.0, 10.9, 0.0, 0.0, 3.0, 88),
    ("Beef mince 5% fat (cooked)", 125, "serving", 153, 26.4, 0.0, 5.4, 0.0, 0.0, 2.3, 75),
    ("Beef steak (grilled)", 170, "steak", 177, 31.0, 0.0, 5.9, 0.0, 0.0, 2.5, 55),
    ("Bacon (grilled back)", 25, "rasher", 287, 24.2, 0.5, 21.0, 0.0, 0.5, 7.8, 1700),
    ("Sausage (pork, grilled)", 55, "sausage", 294, 15.5, 8.5, 22.1, 0.9, 1.5, 8.2, 800),
    ("Ham (sliced)", 30, "slice", 107, 18.4, 1.0, 3.3, 0.0, 1.0, 1.1, 1000),
    ("Salmon fillet (baked)", 140, "fillet", 208, 20.4, 0.0, 13.4, 0.0, 0.0, 2.5, 59),
    ("Cod fillet (baked)", 140, "fillet", 96, 21.5, 0.0, 1.2, 0.0, 0.0, 0.2, 80),
    ("Tuna (tinned in brine, drained)", 100, "small tin", 105, 24.0, 0.0, 0.8, 0.0, 0.0, 0.3, 320),
    ("Prawns (cooked)", 80, "serving", 85, 18.3, 0.2, 1.0, 0.0, 0.0, 0.2, 450),
    ("Fish fingers (grilled)", 84, "3 fingers", 214, 13.0, 19.3, 9.0, 1.0, 0.8, 1.0, 350),
    # -- pulses & plant proteins
    ("Baked beans (tomato sauce)", 210, "half tin", 81, 4.8, 12.5, 0.6, 4.9, 5.0, 0.1, 360),
    ("Lentils (cooked)", 120, "serving", 116, 9.0, 20.1, 0.4, 7.9, 1.8, 0.1, 2),
    ("Chickpeas (tinned, drained)", 120, "serving", 139, 7.2, 21.3, 2.6, 6.4, 0.5, 0.3, 90),
    ("Tofu (firm)", 100, "half block", 118, 12.6, 1.2, 7.0, 0.9, 0.6, 1.0, 12),
    ("Hummus", 50, "2 tbsp", 306, 7.4, 11.6, 25.0, 6.0, 0.8, 3.2, 380),
    # -- fats, nuts & spreads
    ("Olive oil", 11, "tablespoon", 884, 0.0, 0.0, 99.9, 0.0, 0.0, 14.0, 0),
    ("Peanut butter", 16, "tablespoon", 588, 25.1, 20.0, 50.0, 6.0, 9.2, 10.0, 430),
    ("Almonds", 30, "handful", 579, 21.2, 21.6, 49.9, 12.5, 4.4, 3.8, 1),
    ("Honey", 21, "tablespoon", 304, 0.3, 82.4, 0.0, 0.2, 82.1, 0.0, 4),
    ("Jam", 15, "tablespoon", 258, 0.4, 64.0, 0.1, 0.7, 60.0, 0.0, 15),
    ("Mayonnaise", 15, "tablespoon", 680, 1.1, 1.5, 74.6, 0.0, 1.4, 5.7, 500),
    ("Tomato ketchup", 15, "tablespoon", 102, 1.2, 24.0, 0.1, 0.7, 22.8, 0.0, 720),
    # -- sports nutrition
    ("Whey protein powder", 30, "scoop", 380, 76.0, 8.0, 6.0, 1.0, 5.0, 2.5, 350),
    ("Protein bar", 60, "bar", 350, 30.0, 33.0, 11.0, 8.0, 3.5, 5.0, 300),
    # -- meals & treats
    ("Cheese and tomato pizza", 110, "slice", 266, 11.0, 33.0, 9.7, 2.3, 3.6, 4.5, 560),
    ("Vegetable soup", 300, "bowl", 43, 1.2, 6.8, 1.2, 1.5, 2.6, 0.2, 260),
    ("Yorkshire pudding", 30, "pudding", 211, 6.6, 24.6, 9.9, 1.0, 2.5, 1.3, 250),
    ("Gravy (from granules)", 70, "ladle", 34, 0.6, 4.5, 1.5, 0.2, 0.4, 0.6, 400),
    ("Milk chocolate", 25, "four squares", 535, 7.7, 57.0, 30.0, 2.1, 54.0, 18.5, 80),
    ("Crisps (ready salted)", 25, "small bag", 530, 6.5, 50.0, 33.0, 4.0, 0.6, 3.5, 520),
    # -- drinks
    ("Orange juice", 200, "glass", 45, 0.7, 10.4, 0.1, 0.1, 8.9, 0.0, 1),
    ("Coffee with semi-skimmed milk", 250, "mug", 7, 0.5, 0.7, 0.2, 0.0, 0.7, 0.1, 6),
    ("Tea with semi-skimmed milk", 250, "mug", 5, 0.4, 0.5, 0.2, 0.0, 0.5, 0.1, 4),
    ("Latte (semi-skimmed)", 300, "medium latte", 29, 2.4, 3.3, 1.1, 0.0, 3.3, 0.7, 30),
    ("Lager (4%)", 568, "pint", 40, 0.3, 3.1, 0.0, 0.0, 0.1, 0.0, 4),
    ("Red wine", 175, "medium glass", 85, 0.1, 2.6, 0.0, 0.0, 0.6, 0.0, 4),
    ("White wine (dry)", 175, "medium glass", 82, 0.1, 2.6, 0.0, 0.0, 1.0, 0.0, 5),
)

GENERIC_FOODS: list[dict] = [dict(zip(_FIELDS, row, strict=True)) for row in _ROWS]


def search_generics(q: str, limit: int = 10) -> list[dict]:
    """Case-insensitive match against the generic list, best matches first.

    Ranking: whole-name prefix beats word prefix beats plain substring, so
    "chi" surfaces "Chicken breast" and "Chickpeas" before "Oven chips".
    """
    q = (q or "").strip().lower()
    if not q:
        return []
    ranked: list[tuple[int, str, dict]] = []
    for item in GENERIC_FOODS:
        name = item["name"].lower()
        words = name.replace("(", " ").replace(")", " ").replace(",", " ").split()
        if name.startswith(q):
            rank = 0
        elif any(word.startswith(q) for word in words):
            rank = 1
        elif q in name:
            rank = 2
        else:
            continue
        ranked.append((rank, name, item))
    ranked.sort(key=lambda entry: (entry[0], entry[1]))
    return [
        {**item, "source_provider": "generic", "source_confidence": "medium"}
        for _, _, item in ranked[:limit]
    ]
