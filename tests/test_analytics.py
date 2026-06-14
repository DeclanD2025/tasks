from __future__ import annotations

from app import services
from app.analytics import generate_insights
from app.analytics.engine import RULES
from app.db.database import session_scope
from app.db.models import Insight


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
