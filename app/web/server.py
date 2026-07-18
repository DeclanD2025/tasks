"""ORION web server: the personal OS served as a PWA.

Run:
    uv run orion-web                 # binds 127.0.0.1:8321 (this Mac only)
    ORION_WEB_HOST=0.0.0.0 uv run orion-web   # reachable from your phone on the LAN

Every screen renders the same deterministic read models the desktop app uses
(``app.domains.personal_os`` and friends); the web layer contains no scoring
or interpretation of its own. Routers live in ``app.web.routes`` — one module
per surface — and shared plumbing (templates, nav, auth, the offline write
protocol) in ``app.web.context``.

Deployment (Fly.io / Railway / Render — anything that runs a container) is
documented in ``docs/DEPLOY.md``. Relevant environment variables:
    ORION_WEB_HOST / ORION_WEB_PORT    bind address
    ORION_WEB_SECRET                   session-signing secret (containers)
    ORION_WEB_SECURE=1                 HTTPS-only cookies + HSTS (behind TLS)
    ORION_UNLOCK_PASSPHRASE            required in production (ORION_ENV)
    ORION_INGEST_TOKEN                 enables POST /api/ingest/hae (HAE push)
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.core.logging import configure_logging, get_logger
from app.core.security import verify_unlock
from app.db.database import init_db
from app.web.auth import SESSION_COOKIE, issue_token
from app.web.context import authed, page, queued_request
from app.web.presentation import delta as _delta  # noqa: F401 — public test contract
from app.web.routes import ALL_ROUTERS
from app.web import ui_next

log = get_logger(__name__)

_HERE = Path(__file__).parent

# Paths reachable without a session: PWA plumbing, login, health checks, and
# the token-guarded HAE push endpoint (it authenticates itself).
_OPEN_PATHS = {
    "/login",
    "/healthz",
    "/manifest.webmanifest",
    "/service-worker.js",
    "/api/ingest/hae",
}


def _secure_cookies() -> bool:
    return os.environ.get("ORION_WEB_SECURE", "") == "1"


@asynccontextmanager
async def _lifespan(_app: FastAPI):  # pragma: no cover - trivial
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="ORION", docs_url=None, redoc_url=None, openapi_url=None, lifespan=_lifespan
    )
    app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")

    # The redesigned Next UI, if it has been built. Mounted before the routers
    # so its base path resolves cleanly, and inside the session middleware so
    # it stays behind the passphrase. `_ui_base` is read by the CSP middleware.
    _ui_base = ui_next.mount_next_ui(app) or ""
    if _ui_base == "/":
        _ui_base = ""

    @app.get("/service-worker.js", include_in_schema=False)
    def service_worker():
        return FileResponse(
            _HERE / "static" / "orion-sw.js",
            media_type="text/javascript",
            headers={"Service-Worker-Allowed": "/"},
        )

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest():
        return FileResponse(
            _HERE / "static" / "manifest.webmanifest",
            media_type="application/manifest+json",
        )

    @app.middleware("http")
    async def _security_headers(request: Request, call_next):
        response = await call_next(request)
        # style-src allows inline style attributes: templates size progress
        # bars and factor tracks with computed inline widths. Script-src stays
        # locked to 'self' — no inline handlers exist. Map tiles need img-src
        # for the OSM/Carto hosts; connect-src stays 'self' because every
        # external API is proxied server-side.
        #
        # The Next UI is the one exception: a static export inlines its
        # hydration payload as ~13 <script> blocks and cannot carry a nonce
        # (nonces need SSR). Without 'unsafe-inline' those are blocked and the
        # app renders but never hydrates. The relaxation is scoped to the UI
        # base path only, so the Jinja app keeps the strict policy. Acceptable
        # here because that UI renders only first-party data — it never
        # interpolates user-supplied HTML — and sits behind the session gate.
        script_src = "script-src 'self'"
        if _ui_base and request.url.path.startswith(_ui_base):
            script_src = "script-src 'self' 'unsafe-inline'"
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            f"{script_src}; "
            "img-src 'self' data: https://*.basemaps.cartocdn.com "
            "https://tile.openstreetmap.org; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if _secure_cookies():
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    @app.middleware("http")
    async def _require_session(request: Request, call_next):
        path = request.url.path
        open_path = path.startswith("/static") or path in _OPEN_PATHS
        if not open_path and not authed(request):
            if queued_request(request):
                return JSONResponse({"status": "login_required"}, status_code=401)
            return RedirectResponse("/login", status_code=303)
        return await call_next(request)

    # ------------------------------------------------------------------ auth
    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request):
        if authed(request):
            return RedirectResponse("/", status_code=303)
        return page(request, "login.html", "login", error=None)

    @app.post("/login")
    async def login(request: Request, passphrase: str = Form("")):
        if not verify_unlock(passphrase):
            await asyncio.sleep(0.6)  # slow brute-force attempts
            return page(request, "login.html", "login", error="Passphrase not recognised.")
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            SESSION_COOKIE,
            issue_token(),
            httponly=True,
            samesite="lax",
            max_age=30 * 24 * 3600,
            secure=_secure_cookies(),
        )
        return response

    @app.post("/logout")
    def logout():
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE)
        return response

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    for router in ALL_ROUTERS:
        app.include_router(router)

    return app


def main() -> None:  # pragma: no cover - process entry point
    import uvicorn

    configure_logging()
    init_db()
    host = os.environ.get("ORION_WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("ORION_WEB_PORT", "8321"))
    log.info("ORION web starting on http://%s:%s", host, port)
    uvicorn.run(create_app(), host=host, port=port, log_level="info", proxy_headers=True)


if __name__ == "__main__":  # pragma: no cover
    main()
