"""Browser-style regression test for the Health / Body Telemetry page.

Uses the existing FastAPI TestClient so no extra browser dependencies are
needed. Verifies that the redesigned observatory layout renders with the
readiness hero, score contributions, primary signals, progressive
disclosure, and deep-dive actions.
"""

from __future__ import annotations

import re
from datetime import date
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from app import services
from app.db.database import session_scope
from app.db.models import Domain, HealthMetricDaily, Insight, InsightSeverity
from app.web.server import create_app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture()
def authed(client: TestClient) -> TestClient:
    response = client.post("/login", data={"passphrase": "orion"}, follow_redirects=False)
    assert response.status_code == 303
    return client


class _PrimaryGridParser(HTMLParser):
    """Extract text and count signal cards inside the primary-signals grid."""

    def __init__(self) -> None:
        super().__init__()
        self._in_grid = False
        self._grid_depth = 0
        self._texts: list[str] = []
        self.signal_count = 0

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        cls = attrs_dict.get("class", "")
        if tag == "div" and cls == "health-primary-grid":
            self._in_grid = True
            self._grid_depth = 1
            return
        if self._in_grid:
            self._grid_depth += 1
            if tag == "article" and "health-signal" in cls:
                self.signal_count += 1

    def handle_endtag(self, tag):
        if not self._in_grid:
            return
        self._grid_depth -= 1
        if self._grid_depth == 0:
            self._in_grid = False

    def handle_data(self, data):
        if self._in_grid:
            self._texts.append(data)

    @property
    def text(self) -> str:
        return " ".join(self._texts)


def _parse_primary_grid(page: str) -> _PrimaryGridParser:
    parser = _PrimaryGridParser()
    parser.feed(page)
    return parser


def _findings_section_text(page: str) -> str:
    """Extract the text content of the Findings section."""
    # Match from the Findings heading to the closing </section> tag.
    match = re.search(r"<h2>Findings</h2>.*?</section>", page, re.DOTALL)
    if not match:
        return ""
    # Strip HTML tags to leave just the text.
    return re.sub(r"<[^>]+>", " ", match.group(0))


def test_health_page_renders_observatory_layout(authed: TestClient):
    """Regression test for the redesigned Health / Body Telemetry page."""
    response = authed.get("/health")
    assert response.status_code == 200
    text = response.text

    # Readiness hero
    assert '<section class="health-hero"' in text
    assert "Readiness" in text
    assert "health-hero-title" in text
    assert "health-hero-score" in text
    # A numeric readiness score is rendered when data is available.
    assert re.search(r'health-hero-number">\s*\d+\s*</span>', text) is not None
    assert "data {{ snap.data_quality }}" not in text  # Jinja should have rendered

    # Score contributions (factors), not generic progress bars
    assert '<div class="health-factors">' in text
    assert "What’s driving readiness" in text
    assert "health-factor-delta" in text
    # At least one factor shows a signed contribution.
    assert 'class="health-factor-delta positive"' in text or 'class="health-factor-delta negative"' in text

    # Primary signals: at most three, with Sleep and HRV prioritised
    assert '<div class="health-primary-grid">' in text
    primary = _parse_primary_grid(text)
    assert "Sleep" in primary.text
    assert "HRV" in primary.text
    assert primary.signal_count <= 3, (
        f"expected at most 3 primary signals, found {primary.signal_count}"
    )

    # Progressive disclosure for secondary signals
    assert '<details class="health-more">' in text
    assert "More signals" in text
    # The disclosure should contain compact secondary signal cards when data exists.
    assert 'class="health-signal compact' in text

    # Sleep debt section
    assert "Sleep debt" in text

    # Deep dives
    assert "Deep dives" in text
    assert 'data-detail="hrv"' in text
    assert 'data-detail="resting_hr"' in text

    # Legacy /recovery path renders the same page
    legacy = authed.get("/recovery")
    assert legacy.status_code == 200
    assert '<section class="health-hero"' in legacy.text


def test_blood_pressure_deep_dive_exposes_systolic_diastolic_facts(authed: TestClient):
    """The Blood Pressure deep-dive button is present and the detail API exposes the pair."""
    uid = services.get_default_user_id()
    with session_scope() as s:
        row = s.query(HealthMetricDaily).filter_by(user_id=uid, day=date.today()).first()
        if row is None:
            row = HealthMetricDaily(user_id=uid, day=date.today())
            s.add(row)
        row.extra = {**(row.extra or {}), "bp_systolic": 120, "bp_diastolic": 80}

    # The Health page advertises a Blood Pressure deep-dive action in the Deep dives section.
    page = authed.get("/health")
    assert page.status_code == 200
    assert 'data-detail="blood_pressure"' in page.text
    assert "Blood Pressure" in page.text
    # Scope the button check to the Deep dives section.
    deep_dives_start = page.text.find('<div class="health-deepdives">')
    assert deep_dives_start != -1
    deep_dives_html = page.text[deep_dives_start:]
    assert 'data-detail="blood_pressure"' in deep_dives_html
    assert "Blood Pressure" in deep_dives_html

    # The detail API returns the combined reading and facts.
    detail = authed.get("/api/detail/blood_pressure")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["kind"] == "blood_pressure"
    assert payload["title"] == "Blood pressure"
    assert payload["latest"] == "120/80"

    facts = {f["label"]: f for f in payload["facts"]}
    assert "Systolic" in facts
    assert "Diastolic" in facts
    assert facts["Systolic"]["value"] == "120 mmHg"
    assert facts["Diastolic"]["value"] == "80 mmHg"


def test_health_page_renders_health_insights(authed: TestClient):
    """Health-domain insights generated by the analytics engine appear in the Findings section."""
    uid = services.get_default_user_id()
    with session_scope() as s:
        s.add(
            Insight(
                user_id=uid,
                domain=Domain.health,
                severity=InsightSeverity.warning,
                title="Blood pressure is elevated over the last 7 days.",
                body="Average 135/85 mmHg",
                rule_key="blood_pressure_elevated",
                metric_value=135.0,
            )
        )

    response = authed.get("/health")
    assert response.status_code == 200

    # Scope the check to the Findings section.
    findings_text = _findings_section_text(response.text)
    assert "Findings" in findings_text
    assert "Blood pressure is elevated over the last 7 days." in findings_text
    assert "Average 135/85 mmHg" in findings_text
