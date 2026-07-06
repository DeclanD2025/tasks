from __future__ import annotations

from app.domains.mental_health.mental_health_service import build_reflection


def test_reflection_detects_common_traps():
    result = build_reflection("This will be a disaster and everyone thinks I am a failure.")
    labels = {hit.label for hit in result.trap_hits}

    assert "Catastrophising" in labels
    assert "Mind-reading" in labels
    assert result.act_prompts


def test_reflection_recommends_regulation_for_avoidance():
    result = build_reflection("I want to avoid this and scroll instead.")

    assert result.regulation.key == "urge_surfing"
    assert "urgent" in result.safety_note.lower()
