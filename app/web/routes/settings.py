"""Settings: targets, location, units, appearance, integration adapters."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.domains import settings_service
from app.web.context import page, user_id

router = APIRouter()


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, saved: str = ""):
    uid = user_id()
    values = settings_service.get_settings_snapshot(uid)
    groups: dict[str, list] = {}
    for spec in settings_service.SETTING_SPECS:
        groups.setdefault(spec.group, []).append(spec)
    return page(
        request,
        "settings.html",
        "settings",
        values=values,
        groups=groups,
        group_labels=settings_service.GROUP_LABELS,
        saved=bool(saved),
    )


@router.post("/settings")
async def settings_save(request: Request):
    form = await request.form()
    settings_service.set_values(user_id(), {k: str(v) for k, v in form.items()})
    return RedirectResponse("/settings?saved=1", status_code=303)
