"""Web routers, one module per surface. ``server.create_app`` mounts them all."""

from app.web.routes import (
    api,
    api_v2,
    api_v2_brief,
    api_v2_strength,
    calendar_orbit,
    data,
    health,
    mind,
    money,
    nutrition,
    route_atlas,
    settings,
    strength,
    tasks,
    today,
    training,
)

ALL_ROUTERS = [
    today.router,
    training.router,
    strength.router,
    health.router,
    nutrition.router,
    route_atlas.router,
    calendar_orbit.router,
    mind.router,
    tasks.router,
    money.router,
    data.router,
    settings.router,
    api.router,
    api_v2.router,
    api_v2_brief.router,
    api_v2_strength.router,
]
