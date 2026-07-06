"""Nutrition domain: zero-subscription food logging.

Three data layers feed one local food library (``NutritionFood``):

* ``generics`` — curated UK reference foods, always available offline;
* ``off_client`` — Open Food Facts barcode/search (free, keyless, best-effort);
* user corrections — which permanently win over both.

``service`` is the only module the web layer should import.
"""
