"""Open Food Facts client — free, keyless, best-effort.

Maps OFF's nutriment keys onto the per-100g columns of ``NutritionFood`` so a
scanned product drops straight into the local library. By contract nothing in
this module raises: OFF is a volunteer-run upstream and its flakiness must
degrade to "no result", never to a broken page.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.logging import get_logger

log = get_logger(__name__)

_BASE = "https://world.openfoodfacts.org"
_TIMEOUT = httpx.Timeout(6.0)
_HEADERS = {"User-Agent": "ORION-personal/1.0 (private dashboard)"}
_FIELDS = "product_name,brands,serving_quantity,serving_size,nutriments,code"

# OFF nutriment key -> NutritionFood column (all per 100 g).
_NUTRIMENT_MAP = {
    "energy-kcal_100g": "calories_100g",
    "proteins_100g": "protein_100g",
    "carbohydrates_100g": "carbs_100g",
    "fat_100g": "fat_100g",
    "fiber_100g": "fibre_100g",
    "sugars_100g": "sugar_100g",
    "saturated-fat_100g": "saturated_fat_100g",
}


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _map_product(product: dict) -> dict | None:
    """Normalise one OFF product dict; None when it has no usable name."""
    name = str(product.get("product_name") or "").strip()
    if not name:
        return None
    nutriments = product.get("nutriments") or {}
    mapped = {ours: _as_float(nutriments.get(theirs)) for theirs, ours in _NUTRIMENT_MAP.items()}
    # OFF reports sodium in grams; UK labels usually carry salt (sodium x 2.5).
    sodium_g = _as_float(nutriments.get("sodium_100g"))
    if sodium_g is None:
        salt_g = _as_float(nutriments.get("salt_100g"))
        sodium_g = salt_g / 2.5 if salt_g is not None else None
    mapped["sodium_mg_100g"] = round(sodium_g * 1000, 1) if sodium_g is not None else None

    core = ("calories_100g", "protein_100g", "carbs_100g", "fat_100g")
    if all(mapped[key] is not None for key in core):
        confidence = "high"
    elif mapped["calories_100g"] is not None:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "name": name,
        "brand": str(product.get("brands") or "").split(",")[0].strip(),
        "barcode": str(product.get("code") or "").strip() or None,
        "serving_size": _as_float(product.get("serving_quantity")),
        "serving_unit": str(product.get("serving_size") or "").strip() or "serving",
        **mapped,
        "source_provider": "off",
        "source_confidence": confidence,
    }


def lookup_barcode(barcode: str) -> dict | None:
    """Fetch one product by barcode; None on miss or any upstream failure."""
    barcode = (barcode or "").strip()
    if not barcode:
        return None
    try:
        with httpx.Client(timeout=_TIMEOUT, headers=_HEADERS) as client:
            response = client.get(
                f"{_BASE}/api/v2/product/{barcode}.json", params={"fields": _FIELDS}
            )
            response.raise_for_status()
            product = response.json().get("product") or {}
        return _map_product(product)
    except Exception as exc:  # noqa: BLE001 — by contract this client never raises
        log.warning("OFF barcode lookup failed for %s: %s", barcode, exc)
        return None


def search_products(q: str, limit: int = 12) -> list[dict]:
    """Free-text product search; [] on any failure or when nothing is usable."""
    q = (q or "").strip()
    if not q:
        return []
    try:
        with httpx.Client(timeout=_TIMEOUT, headers=_HEADERS) as client:
            response = client.get(
                f"{_BASE}/cgi/search.pl",
                params={
                    "search_terms": q,
                    "search_simple": 1,
                    "action": "process",
                    "json": 1,
                    "page_size": limit,
                    "fields": _FIELDS,
                },
            )
            response.raise_for_status()
            products = response.json().get("products") or []
        results = []
        for product in products:
            mapped = _map_product(product)
            # A hit without a name or calories cannot be logged meaningfully.
            if mapped is not None and mapped["calories_100g"] is not None:
                results.append(mapped)
        return results[:limit]
    except Exception as exc:  # noqa: BLE001 — by contract this client never raises
        log.warning("OFF search failed for %r: %s", q, exc)
        return []
