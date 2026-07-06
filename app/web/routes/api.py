"""JSON APIs: metric drilldowns, external signals, nutrition lookups.

Everything here is consumed by ORION's own front-end (drawers, charts, the
weather pill, the barcode scanner). Responses are plain JSON and always
succeed structurally — upstream failures arrive as ``{"ok": false, ...}``
rather than as HTTP errors, so the UI can render a quiet fallback.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.domains import personal_os, settings_service
from app.domains.health import metric_details
from app.integrations import external_signals as signals
from app.web.context import user_id

router = APIRouter()


@router.get("/api/today")
def api_today():
    return JSONResponse(jsonable_encoder(personal_os.get_today_snapshot(user_id())))


@router.get("/api/detail/{kind}")
def api_detail(kind: str, days: int = 90):
    detail = metric_details.get_metric_detail(user_id(), kind, days=days)
    if detail is None:
        return JSONResponse({"error": "unknown metric"}, status_code=404)
    return JSONResponse(jsonable_encoder(detail))


def _location(uid: int) -> tuple[float, float, str]:
    values = settings_service.get_settings_snapshot(uid)
    return (
        float(values["location_lat"]),
        float(values["location_lon"]),
        str(values["location_name"]),
    )


@router.get("/api/signals/weather")
def api_weather():
    uid = user_id()
    lat, lon, name = _location(uid)
    weather = signals.get_weather(lat, lon)
    payload = jsonable_encoder(
        {
            "ok": weather.ok,
            "stale": weather.stale,
            "age": weather.age_label,
            "location": name,
            "error": weather.error,
            "data": weather.payload,
        }
    )
    if weather.ok and weather.payload.get("current"):
        code = weather.payload["current"].get("weather_code")
        label, glyph = signals.service.describe_wmo(code)
        payload["summary"] = {
            "temp": round(weather.payload["current"].get("temperature_2m", 0)),
            "label": label,
            "glyph": glyph,
        }
    return JSONResponse(payload)


@router.get("/api/signals/air")
def api_air():
    uid = user_id()
    lat, lon, name = _location(uid)
    air = signals.get_air_quality(lat, lon)
    current = air.payload.get("current") or {}
    return JSONResponse(jsonable_encoder({
        "ok": air.ok,
        "stale": air.stale,
        "age": air.age_label,
        "location": name,
        "error": air.error,
        "aqi": current.get("european_aqi"),
        "band": signals.service.aqi_band(current.get("european_aqi")),
        "pm2_5": current.get("pm2_5"),
        "pm10": current.get("pm10"),
        "data": air.payload,
    }))


@router.get("/api/nutrition/search")
def api_nutrition_search(q: str = ""):
    from app.domains.nutrition import service as nutrition

    q = q.strip()
    if len(q) < 2:
        return JSONResponse({"local": [], "generic": [], "off": []})
    return JSONResponse(jsonable_encoder(nutrition.search(user_id(), q)))


@router.get("/api/nutrition/barcode/{barcode}")
def api_nutrition_barcode(barcode: str):
    from app.domains.nutrition import service as nutrition

    barcode = "".join(ch for ch in barcode if ch.isdigit())[:32]
    if not barcode:
        return JSONResponse({"found": False, "error": "No barcode supplied."})
    result = nutrition.barcode_lookup(user_id(), barcode)
    if result is None:
        return JSONResponse({
            "found": False,
            "barcode": barcode,
            "error": "Not in Open Food Facts — add it manually and it will be "
                     "remembered.",
        })
    return JSONResponse(jsonable_encoder({"found": True, "food": result}))
