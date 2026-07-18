"""The Next.js static export mount (app/web/ui_next.py).

The export is a build artifact, so these tests skip cleanly when nobody has run
`pnpm build` — but the security-relevant behaviour (session gating, and the CSP
relaxation being scoped to the UI base path) is asserted whenever it is present.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.web import ui_next
from app.web.server import create_app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture()
def authed(client: TestClient) -> TestClient:
    response = client.post("/login", data={"passphrase": "orion"}, follow_redirects=False)
    assert response.status_code == 303
    return client


built = pytest.mark.skipif(
    ui_next.find_ui_dir() is None,
    reason="Next UI not built (run `pnpm build` in frontend/)",
)


def test_missing_build_is_not_fatal():
    """A checkout without a built UI still yields a working app."""
    app = create_app()
    assert any(route.path == "/static" for route in app.routes)


@built
def test_ui_requires_a_session(client: TestClient):
    """The redesigned UI is behind the passphrase, like every other page."""
    response = client.get(f"{ui_next.ui_base_path()}/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


@built
def test_ui_serves_index_when_authed(authed: TestClient):
    response = authed.get(f"{ui_next.ui_base_path()}/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


@built
def test_root_lands_on_the_redesigned_ui(authed: TestClient):
    """Visiting the bare domain shows the new UI, not the Jinja today page."""
    response = authed.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == f"{ui_next.ui_base_path()}/"


@built
def test_jinja_today_survives_at_its_own_path(authed: TestClient):
    """Handing "/" over must not strip access to the real-data pages."""
    response = authed.get("/today")
    assert response.status_code == 200
    assert "ORION" in response.text


@built
def test_root_redirect_still_requires_a_session(client: TestClient):
    """The redirect must not become an unauthenticated hole at the root."""
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


@built
def test_csp_allows_inline_scripts_only_under_the_ui_base_path(authed: TestClient):
    """A static export inlines its hydration payload and cannot use a nonce.

    The relaxation must not leak to the Jinja app, which has no inline scripts
    and should stay on the strict policy.
    """
    ui = authed.get(f"{ui_next.ui_base_path()}/")
    assert "script-src 'self' 'unsafe-inline'" in ui.headers["content-security-policy"]

    legacy = authed.get("/health")
    csp = legacy.headers["content-security-policy"]
    assert "script-src 'self';" in csp
    assert "unsafe-inline" not in csp.split("script-src")[1].split(";")[0]
