from __future__ import annotations

from datetime import date, timedelta

from app import services
from app.analytics import generate_insights
from app.analytics.engine import RULES, rule_blood_pressure_elevation
from app.db.database import session_scope
from app.db.models import HealthMetricDaily, Insight, UserSetting


def test_insight_rules_are_pure_and_return_lists():
    uid = services.get_default_user_id()
    for rule in RULES:
        result = rule(uid)
        assert isinstance(result, list)


def test_generate_insights_persists_and_is_deterministic():
    uid = services.get_default_user_id()
    count_a = generate_insights(uid)
    count_b = generate_insights(uid)  # replace=True by default
    assert count_a == count_b  # deterministic given the same data

    with session_scope() as s:
        rows = s.query(Insight).filter_by(user_id=uid).count()
    assert rows == count_b


def test_no_llm_dependency_imported():
    # Guard the core principle: the analytics engine must not import a hosted
    # LLM client.
    import app.analytics.engine as engine

    src = engine.__file__
    text = open(src).read().lower()
    for banned in ("anthropic", "openai", "import claude"):
        assert banned not in text


def _seed_blood_pressure(user_id: int, values: list[tuple[date, float, float]]) -> None:
    with session_scope() as s:
        for day, systolic, diastolic in values:
            row = s.query(HealthMetricDaily).filter_by(user_id=user_id, day=day).first()
            if row is None:
                row = HealthMetricDaily(user_id=user_id, day=day)
                s.add(row)
            row.extra = {
                "bp_systolic": systolic,
                "bp_diastolic": diastolic,
            }


def _reset_bp_settings(user_id: int) -> None:
    """Delete custom BP threshold settings and any seeded BP rows for a user."""
    with session_scope() as s:
        s.query(UserSetting).filter(
            UserSetting.user_id == user_id,
            UserSetting.key.in_(
                [
                    "bp_elevation_systolic",
                    "bp_elevation_diastolic",
                    "bp_delta_systolic",
                    "bp_delta_diastolic",
                ]
            ),
        ).delete(synchronize_session=False)
        for row in s.query(HealthMetricDaily).filter_by(user_id=user_id):
            if row.extra and ("bp_systolic" in row.extra or "bp_diastolic" in row.extra):
                s.delete(row)


def test_blood_pressure_elevation_flags_sustained_high_reading():
    uid = services.get_default_user_id()
    _reset_bp_settings(uid)
    today = date.today()
    values = [(today - timedelta(days=i), 135, 85) for i in range(7)]
    _seed_blood_pressure(uid, values)

    drafts = rule_blood_pressure_elevation(uid)
    assert len(drafts) == 1
    draft = drafts[0]
    assert draft.rule_key == "blood_pressure_elevated"
    assert draft.severity.value == "warning"
    assert "elevated" in draft.title.lower()
    assert "135/85" in draft.body


def test_blood_pressure_elevation_flags_unusual_delta():
    uid = services.get_default_user_id()
    _reset_bp_settings(uid)
    today = date.today()
    # Prior week is normal; recent week jumps up by >10/6 mmHg but stays below the
    # sustained-elevation threshold so only the delta condition fires.
    values = [
        *((today - timedelta(days=i), 118, 72) for i in range(7, 14)),
        *((today - timedelta(days=i), 129, 79) for i in range(7)),
    ]
    _seed_blood_pressure(uid, values)

    drafts = rule_blood_pressure_elevation(uid)
    assert len(drafts) == 1
    draft = drafts[0]
    assert draft.rule_key == "blood_pressure_jump"
    assert draft.severity.value == "info"
    assert "jumped" in draft.title.lower()


def test_blood_pressure_elevation_is_silent_when_readings_are_stable():
    uid = services.get_default_user_id()
    _reset_bp_settings(uid)
    today = date.today()
    values = [
        *((today - timedelta(days=i), 118, 76) for i in range(7, 14)),
        *((today - timedelta(days=i), 120, 78) for i in range(7)),
    ]
    _seed_blood_pressure(uid, values)

    drafts = rule_blood_pressure_elevation(uid)
    assert drafts == []


def test_blood_pressure_elevation_uses_custom_elevation_thresholds():
    """User-configurable elevation thresholds override the defaults."""
    uid = services.get_default_user_id()
    _reset_bp_settings(uid)
    from app.domains import settings_service

    settings_service.set_values(
        uid,
        {
            "bp_elevation_systolic": "140",
            "bp_elevation_diastolic": "90",
        },
    )

    today = date.today()
    # Seed 14 days at the same level so neither elevation nor delta fires.
    values = [(today - timedelta(days=i), 135, 85) for i in range(14)]
    _seed_blood_pressure(uid, values)

    drafts = rule_blood_pressure_elevation(uid)
    assert drafts == []


def test_blood_pressure_elevation_uses_custom_delta_thresholds():
    """User-configurable delta thresholds override the defaults."""
    uid = services.get_default_user_id()
    _reset_bp_settings(uid)
    from app.domains import settings_service

    # Raise delta thresholds so the default-jumping 129/79 vs 118/72 reading is no
    # longer flagged.
    settings_service.set_values(
        uid,
        {
            "bp_delta_systolic": "15",
            "bp_delta_diastolic": "10",
        },
    )

    today = date.today()
    values = [
        *((today - timedelta(days=i), 118, 72) for i in range(7, 14)),
        *((today - timedelta(days=i), 129, 79) for i in range(7)),
    ]
    _seed_blood_pressure(uid, values)

    drafts = rule_blood_pressure_elevation(uid)
    assert drafts == []


def test_blood_pressure_elevation_respects_lowered_elevation_threshold():
    """Lowering the elevation threshold makes the rule more sensitive."""
    uid = services.get_default_user_id()
    _reset_bp_settings(uid)
    from app.domains import settings_service

    settings_service.set_values(
        uid,
        {
            "bp_elevation_systolic": "120",
            "bp_elevation_diastolic": "80",
        },
    )

    today = date.today()
    # 125/78 is below the default 130/80 threshold but above the custom 120/80.
    values = [(today - timedelta(days=i), 125, 78) for i in range(7)]
    _seed_blood_pressure(uid, values)

    drafts = rule_blood_pressure_elevation(uid)
    assert len(drafts) == 1
    draft = drafts[0]
    assert draft.rule_key == "blood_pressure_elevated"
    assert "125/78" in draft.body


def test_generate_insights_persists_blood_pressure_elevation():
    """Running generate_insights end-to-end writes the BP insight to the table."""
    uid = services.get_default_user_id()
    _reset_bp_settings(uid)
    today = date.today()
    values = [(today - timedelta(days=i), 135, 85) for i in range(7)]
    _seed_blood_pressure(uid, values)

    count = generate_insights(uid)
    assert count > 0

    with session_scope() as s:
        rows = (
            s.query(Insight)
            .filter_by(user_id=uid, rule_key="blood_pressure_elevated")
            .all()
        )

    assert len(rows) == 1
    row = rows[0]
    assert row.domain.value == "health"
    assert row.severity.value == "warning"
    assert "elevated" in row.title.lower()
    assert "135/85" in row.body
    assert row.metric_value == 135.0
