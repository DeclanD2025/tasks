"""Route Atlas: mapped runs, attempts, personal bests, GPX in/out."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.domains.fitness import gpx
from app.domains.fitness import route_service as routes
from app.web.context import page, user_id

router = APIRouter()


def _workout_map(uid: int, limit: int = 20) -> list[dict]:
    """Recent GPS workouts with their route-assignment state and suggestions."""
    assigned: dict[int, int] = {}
    for route in routes.list_routes(uid):
        dashboard = routes.get_route_dashboard(uid, route.id)
        if dashboard:
            for attempt in dashboard.attempts:
                assigned[attempt.workout_id] = route.id
    out = []
    for workout in routes.list_workouts(uid, limit=limit * 3):
        if len(workout.route_geometry) < 2:
            continue
        suggestions = (
            routes.possible_route_matches(uid, workout.id, limit=1)
            if workout.id not in assigned else []
        )
        out.append({
            "workout": workout,
            "route_id": assigned.get(workout.id),
            "suggestion": suggestions[0] if suggestions else None,
            "pace": routes.format_pace(
                routes.calculate_pace(workout.duration_seconds, workout.distance_meters)
            ),
            "duration": routes.format_duration(workout.duration_seconds),
        })
        if len(out) >= limit:
            break
    return out


@router.get("/routes", response_class=HTMLResponse)
def atlas(request: Request):
    uid = user_id()
    all_routes = routes.list_routes(uid)
    return page(
        request,
        "routes.html",
        "routes",
        routes=all_routes,
        workouts=_workout_map(uid),
        format_pace=routes.format_pace,
        format_duration=routes.format_duration,
    )


@router.get("/routes/{route_id}", response_class=HTMLResponse)
def route_detail(request: Request, route_id: int):
    uid = user_id()
    dashboard = routes.get_route_dashboard(uid, route_id)
    if dashboard is None:
        return RedirectResponse("/routes", status_code=303)
    # Pace trend across attempts, oldest first, for the drilldown chart.
    pace_series = [
        {"day": a.attempt_date.isoformat(),
         "value": round(a.average_pace_seconds_per_km / 60.0, 2)}
        for a in sorted(dashboard.attempts, key=lambda a: a.attempt_date)
        if a.average_pace_seconds_per_km
    ]
    hr_series = [
        {"day": a.attempt_date.isoformat(), "value": round(a.average_heart_rate)}
        for a in sorted(dashboard.attempts, key=lambda a: a.attempt_date)
        if a.average_heart_rate
    ]
    return page(
        request,
        "route_detail.html",
        "routes",
        dash=dashboard,
        route=dashboard.route,
        pace_series=pace_series,
        hr_series=hr_series,
        format_pace=routes.format_pace,
        format_duration=routes.format_duration,
    )


@router.post("/routes/create")
def route_create(
    name: str = Form(""),
    workout_id: str = Form(""),
    sport_type: str = Form("run"),
    description: str = Form(""),
):
    uid = user_id()
    route_id = routes.create_route(
        uid,
        name=name,
        sport_type=sport_type,
        description=description,
        template_workout_id=int(workout_id) if workout_id.strip() else None,
    )
    return RedirectResponse(f"/routes/{route_id}", status_code=303)


@router.post("/routes/import-gpx")
async def route_import_gpx(file: UploadFile = File(...), name: str = Form("")):
    uid = user_id()
    raw = await file.read()
    result = gpx.create_route_from_gpx(uid, raw, name=name or (file.filename or "").rsplit(".", 1)[0])
    if result["ok"]:
        return RedirectResponse(f"/routes/{result['route_id']}", status_code=303)
    return RedirectResponse("/routes?gpx_error=1", status_code=303)


@router.post("/routes/{route_id}/assign")
def route_assign(route_id: int, workout_id: int = Form(...)):
    routes.assign_workout_to_route(user_id(), workout_id, route_id)
    return RedirectResponse(f"/routes/{route_id}", status_code=303)


@router.post("/routes/{route_id}/delete")
def route_delete(route_id: int):
    routes.delete_route(user_id(), route_id)
    return RedirectResponse("/routes", status_code=303)


# Map data is fetched lazily by the map module, never inlined into HTML.
@router.get("/api/routes/{route_id}/geometry.json")
def route_geometry(route_id: int):
    uid = user_id()
    dashboard = routes.get_route_dashboard(uid, route_id)
    if dashboard is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    geometry = routes.simplify_route_geometry(dashboard.route.route_geometry, max_points=600)
    return JSONResponse({
        "name": dashboard.route.name,
        "points": [{"lat": p["lat"], "lng": p["lng"]} for p in geometry
                   if p.get("lat") is not None],
        "distance_meters": dashboard.route.distance_meters,
    })


@router.get("/api/workouts/{workout_id}/geometry.json")
def workout_geometry(workout_id: int):
    uid = user_id()
    for workout in routes.list_workouts(uid, limit=400):
        if workout.id == workout_id:
            geometry = routes.simplify_route_geometry(workout.route_geometry, max_points=600)
            return JSONResponse({
                "name": workout.title,
                "points": [{"lat": p["lat"], "lng": p["lng"]} for p in geometry
                           if p.get("lat") is not None],
                "distance_meters": workout.distance_meters,
            })
    return JSONResponse({"error": "not found"}, status_code=404)
