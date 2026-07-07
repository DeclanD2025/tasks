"""Data Vault: imports, exports, freshness, source and signal status.

Nothing is trapped: every table exports as CSV, everything as one JSON bundle,
routes and workout traces as GPX. Imports accept HAE JSON exports, GPX tracks,
and plain CSV with a ``day`` column.
"""

from __future__ import annotations

import csv
import hmac
import io
import json
import os
from datetime import date, datetime

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from app.db.database import session_scope
from app.db.models import (
    ActivityMetricDaily,
    CalendarEvent,
    FitnessRoute,
    FoodLog,
    HealthMetricDaily,
    MealTemplate,
    MentalCheckIn,
    MindfulnessSession,
    NutritionFood,
    RouteAttempt,
    StoicEntry,
    Task,
    Workout,
    WorkoutSessionLog,
)
from app.domains import personal_os, settings_service
from app.domains.fitness import gpx
from app.integrations.external_signals import signal_status
from app.integrations.health_auto_export.ingest import apply_payload
from app.web.context import page, user_id

router = APIRouter()

# Exportable tables: name -> (model, columns kept out of CSV because they are
# huge JSON blobs). The JSON bundle always includes every column.
_EXPORT_TABLES = {
    "health_metrics_daily": (HealthMetricDaily, ()),
    "activity_metrics_daily": (ActivityMetricDaily, ()),
    "workouts": (Workout, ("route_geometry", "splits")),
    "food_logs": (FoodLog, ()),
    "nutrition_foods": (NutritionFood, ()),
    "meal_templates": (MealTemplate, ()),
    "mental_checkins": (MentalCheckIn, ()),
    "mindfulness_sessions": (MindfulnessSession, ()),
    "stoic_entries": (StoicEntry, ()),
    "workout_session_logs": (WorkoutSessionLog, ()),
    "tasks": (Task, ()),
    "calendar_events": (CalendarEvent, ()),
    "fitness_routes": (FitnessRoute, ("route_geometry",)),
    "route_attempts": (RouteAttempt, ()),
}

# CSV import: recognised HealthMetricDaily headers (a "day" column is required).
_CSV_HEALTH_COLUMNS = {"sleep_minutes", "hrv_ms", "resting_hr", "weight_kg"}


def _row_dict(row, skip: tuple[str, ...] = ()) -> dict:
    out = {}
    for column in row.__table__.columns:
        if column.name in skip:
            continue
        value = getattr(row, column.name)
        if isinstance(value, (datetime, date)):
            value = value.isoformat()
        out[column.name] = value
    return out


def _user_rows(session, model, uid: int):
    if hasattr(model, "user_id"):
        return session.query(model).filter_by(user_id=uid).all()
    return session.query(model).all()


@router.get("/data", response_class=HTMLResponse)
def data(request: Request, imported: str = ""):
    return _data_page(request, imported=imported)


def _data_page(request: Request, imported: str = "", generated_hae_token: str = ""):
    uid = user_id()
    snapshot = personal_os.get_data_inventory(uid)
    with session_scope() as s:
        counts = {name: len(_user_rows(s, model, uid)) for name, (model, _) in
                  _EXPORT_TABLES.items()}
    report = None
    if imported:
        try:
            report = json.loads(imported)
        except json.JSONDecodeError:
            report = None
    return page(
        request,
        "data.html",
        "data",
        snap=snapshot,
        table_counts=counts,
        signals=signal_status(),
        import_report=report,
        ingest_configured=(
            bool(os.environ.get("ORION_INGEST_TOKEN"))
            or settings_service.hae_ingest_token_configured(uid)
        ),
        generated_hae_token=generated_hae_token,
    )


# ---------------------------------------------------------------------- import
@router.post("/data/import")
async def data_import(file: UploadFile = File(...)):
    uid = user_id()
    raw = await file.read()
    name = (file.filename or "upload").lower()
    report: dict
    if name.endswith(".gpx"):
        result = gpx.create_route_from_gpx(uid, raw, name=file.filename.rsplit(".", 1)[0])
        report = {"kind": "gpx", **result}
    elif name.endswith(".json"):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            report = {"kind": "hae", "ok": False, "error": f"Not valid JSON: {exc}"}
        else:
            with session_scope() as s:
                report = {"kind": "hae", **apply_payload(s, uid, payload)}
    elif name.endswith(".csv"):
        report = _import_health_csv(uid, raw)
    else:
        report = {"kind": "unknown", "ok": False,
                  "error": "Unsupported file type — use HAE .json, .gpx, or .csv."}
    return RedirectResponse(f"/data?imported={json.dumps(report)}", status_code=303)


@router.post("/data/hae-token", response_class=HTMLResponse)
def generate_hae_token(request: Request):
    token = settings_service.generate_hae_ingest_token(user_id())
    return _data_page(request, generated_hae_token=token)


def _import_health_csv(uid: int, raw: bytes) -> dict:
    try:
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        headers = {h.strip().lower() for h in (reader.fieldnames or [])}
    except (UnicodeDecodeError, csv.Error) as exc:
        return {"kind": "csv", "ok": False, "error": f"Unreadable CSV: {exc}"}
    if "day" not in headers or not headers & _CSV_HEALTH_COLUMNS:
        return {
            "kind": "csv", "ok": False,
            "error": "CSV needs a 'day' column plus any of: "
                     + ", ".join(sorted(_CSV_HEALTH_COLUMNS)) + ".",
        }
    written = rejected = 0
    with session_scope() as s:
        for row in reader:
            try:
                day = date.fromisoformat((row.get("day") or "").strip())
            except ValueError:
                rejected += 1
                continue
            target = s.query(HealthMetricDaily).filter_by(user_id=uid, day=day).first()
            if target is None:
                target = HealthMetricDaily(user_id=uid, day=day)
                s.add(target)
            wrote_any = False
            for column in _CSV_HEALTH_COLUMNS:
                value = (row.get(column) or "").strip()
                if not value:
                    continue
                try:
                    setattr(target, column, float(value))
                    wrote_any = True
                except ValueError:
                    pass
            written += 1 if wrote_any else 0
            rejected += 0 if wrote_any else 1
    return {"kind": "csv", "ok": True, "days": written, "rejected": rejected, "error": ""}


# ---------------------------------------------------------------------- export
@router.get("/data/export.json")
def export_all():
    uid = user_id()
    bundle: dict = {"exported_at": datetime.now().isoformat(), "format": "orion-v1"}
    with session_scope() as s:
        for name, (model, _) in _EXPORT_TABLES.items():
            bundle[name] = [_row_dict(r) for r in _user_rows(s, model, uid)]
    return Response(
        json.dumps(bundle, default=str),
        media_type="application/json",
        headers={"Content-Disposition":
                 f'attachment; filename="orion-export-{date.today().isoformat()}.json"'},
    )


@router.get("/data/export/{table}.csv")
def export_table(table: str):
    entry = _EXPORT_TABLES.get(table)
    if entry is None:
        return JSONResponse({"error": "unknown table"}, status_code=404)
    model, skip = entry
    uid = user_id()
    with session_scope() as s:
        rows = [_row_dict(r, skip) for r in _user_rows(s, model, uid)]
    buffer = io.StringIO()
    if rows:
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
                             for k, v in row.items()})
    return Response(
        buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{table}.csv"'},
    )


@router.get("/data/export/routes/{route_id}.gpx")
def export_route_gpx(route_id: int):
    result = gpx.route_gpx(user_id(), route_id)
    if result is None:
        return JSONResponse({"error": "route not found or has no geometry"}, status_code=404)
    filename, xml = result
    return Response(xml, media_type="application/gpx+xml",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/data/export/workouts/{workout_id}.gpx")
def export_workout_gpx(workout_id: int):
    result = gpx.workout_gpx(user_id(), workout_id)
    if result is None:
        return JSONResponse({"error": "workout not found or has no GPS trace"}, status_code=404)
    filename, xml = result
    return Response(xml, media_type="application/gpx+xml",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ------------------------------------------------------------------ HAE ingest
# Open path (session middleware lets it through); guarded by its own bearer
# token so the HAE iOS app can push exports directly to a deployed ORION.
@router.post("/api/ingest/hae")
async def ingest_hae(request: Request):
    uid = user_id()
    expected = os.environ.get("ORION_INGEST_TOKEN", "")
    if not expected and not settings_service.hae_ingest_token_configured(uid):
        return JSONResponse(
            {"status": "disabled",
             "detail": "Set ORION_INGEST_TOKEN or generate a token in Data Vault."},
            status_code=403,
        )
    supplied = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not supplied:
        supplied = request.query_params.get("token", "")
    env_ok = bool(expected) and hmac.compare_digest(supplied, expected)
    db_ok = settings_service.verify_hae_ingest_token(uid, supplied)
    if not (env_ok or db_ok):
        return JSONResponse({"status": "unauthorised"}, status_code=401)
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"status": "error", "detail": "Body must be JSON."},
                            status_code=400)
    with session_scope() as s:
        report = apply_payload(s, uid, payload)
    return JSONResponse({"status": "ok" if report["ok"] else "error", **report},
                        status_code=200 if report["ok"] else 400)
