"""GPX in and out: import route files, export ORION routes/workouts.

ORION's native route geometry is the HAE point list
(``{lat, lng, altitude, timestamp, distance_from_start_m}``); GPX here is a
thin translation layer so routes can arrive from any GPS tool and leave for
any other — no data trapped inside ORION.
"""

from __future__ import annotations

import math
from datetime import datetime
from xml.etree import ElementTree
from xml.sax.saxutils import escape

from app.core.logging import get_logger
from app.db.database import session_scope
from app.db.models import FitnessRoute, Workout
from app.db.models import utcnow

log = get_logger(__name__)

_GPX_NS = "{http://www.topografix.com/GPX/1/1}"
_GPX_NS_10 = "{http://www.topografix.com/GPX/1/0}"


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def parse_gpx(content: bytes | str) -> dict:
    """Parse a GPX track into ORION route geometry.

    Returns {ok, name, points, distance_meters, elevation_gain_meters, error}.
    Tolerates GPX 1.0/1.1, missing elevation/time, and route (<rte>) files.
    """
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        return {"ok": False, "error": f"Not valid GPX/XML: {exc}", "points": []}

    def findall(parent, tag):
        return parent.findall(f".//{_GPX_NS}{tag}") + parent.findall(f".//{_GPX_NS_10}{tag}")

    def findtext(parent, tag):
        node = parent.find(f"{_GPX_NS}{tag}")
        if node is None:
            node = parent.find(f"{_GPX_NS_10}{tag}")
        return node.text if node is not None else None

    raw_points = findall(root, "trkpt") or findall(root, "rtept")
    if not raw_points:
        return {"ok": False, "error": "No track or route points found in file.", "points": []}

    name = None
    for tag in ("trk", "rte", "metadata"):
        for node in findall(root, tag):
            name = findtext(node, "name")
            if name:
                break
        if name:
            break

    points: list[dict] = []
    total = 0.0
    gain = 0.0
    prev = None
    prev_ele = None
    for pt in raw_points:
        try:
            lat, lng = float(pt.attrib["lat"]), float(pt.attrib["lon"])
        except (KeyError, ValueError):
            continue
        ele_text = findtext(pt, "ele")
        time_text = findtext(pt, "time")
        ele = float(ele_text) if ele_text else None
        if prev is not None:
            total += _haversine_m(prev["lat"], prev["lng"], lat, lng)
        if ele is not None and prev_ele is not None and ele > prev_ele:
            gain += ele - prev_ele
        point = {"lat": lat, "lng": lng, "distance_from_start_m": round(total, 1)}
        if ele is not None:
            point["altitude"] = ele
            prev_ele = ele
        if time_text:
            point["timestamp"] = time_text
        points.append(point)
        prev = point

    if len(points) < 2:
        return {"ok": False, "error": "Fewer than two usable points in file.", "points": []}
    return {
        "ok": True,
        "name": (name or "").strip(),
        "points": points,
        "distance_meters": round(total, 1),
        "elevation_gain_meters": round(gain, 1) if gain else None,
        "error": "",
    }


def create_route_from_gpx(user_id: int, content: bytes | str, *, name: str = "",
                          sport_type: str = "run") -> dict:
    """Import a GPX file as a named FitnessRoute. Returns a report dict."""
    parsed = parse_gpx(content)
    if not parsed["ok"]:
        return {"ok": False, "route_id": None, "error": parsed["error"]}
    points = parsed["points"]
    with session_scope() as s:
        route = FitnessRoute(
            user_id=user_id,
            name=(name.strip() or parsed["name"] or "Imported route")[:160],
            sport_type=sport_type if sport_type in {"run", "walk", "cycle"} else "run",
            description="Imported from GPX.",
            distance_meters=parsed["distance_meters"],
            start_lat=points[0]["lat"],
            start_lng=points[0]["lng"],
            end_lat=points[-1]["lat"],
            end_lng=points[-1]["lng"],
            route_geometry=points,
            elevation_gain_meters=parsed["elevation_gain_meters"],
            updated_at=utcnow(),
        )
        s.add(route)
        s.flush()
        return {"ok": True, "route_id": route.id,
                "distance_meters": parsed["distance_meters"],
                "points": len(points), "error": ""}


def _gpx_document(name: str, points: list[dict], started_at: datetime | None = None) -> str:
    """Serialise ORION geometry to GPX 1.1 (track with one segment)."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="ORION" xmlns="http://www.topografix.com/GPX/1/1">',
        f"  <trk><name>{escape(name or 'ORION route')}</name><trkseg>",
    ]
    for p in points:
        lat, lng = p.get("lat"), p.get("lng")
        if lat is None or lng is None:
            continue
        attrs = f'lat="{lat:.7f}" lon="{lng:.7f}"'
        children = ""
        if p.get("altitude") is not None:
            children += f"<ele>{p['altitude']:.1f}</ele>"
        if p.get("timestamp"):
            children += f"<time>{escape(str(p['timestamp']))}</time>"
        lines.append(f"    <trkpt {attrs}>{children}</trkpt>" if children
                     else f"    <trkpt {attrs}/>")
    lines.append("  </trkseg></trk>")
    lines.append("</gpx>")
    return "\n".join(lines)


def route_gpx(user_id: int, route_id: int) -> tuple[str, str] | None:
    """(filename, gpx_xml) for a saved route, or None."""
    with session_scope() as s:
        route = s.get(FitnessRoute, route_id)
        if route is None or route.user_id != user_id or not route.route_geometry:
            return None
        safe = "".join(c if c.isalnum() or c in "-_ " else "" for c in route.name).strip()
        return (f"{safe or 'route'}.gpx", _gpx_document(route.name, route.route_geometry))


def workout_gpx(user_id: int, workout_id: int) -> tuple[str, str] | None:
    """(filename, gpx_xml) for an imported workout's GPS trace, or None."""
    with session_scope() as s:
        workout = s.get(Workout, workout_id)
        if workout is None or workout.user_id != user_id or not workout.route_geometry:
            return None
        day = workout.started_at.date().isoformat() if workout.started_at else "workout"
        return (f"{day}-{workout.sport_type}.gpx",
                _gpx_document(workout.title, workout.route_geometry, workout.started_at))
