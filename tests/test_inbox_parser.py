from __future__ import annotations

from datetime import date

from app.domains.productivity import inbox_parser
from app.domains.productivity.inbox_parser import parseInboxText, parse_inbox_text


def test_parser_splits_brain_dump_and_removes_filler():
    suggestions = parse_inbox_text(
        "I need to call in sick tomorrow, also remember to do BAE interview today",
        today=date(2026, 6, 29),
    )

    assert [s.title for s in suggestions] == ["Call in sick", "Do BAE interview"]
    assert suggestions[0].due_date == date(2026, 6, 30)
    assert suggestions[1].due_date == date(2026, 6, 29)
    assert suggestions[1].today is True
    assert suggestions[1].area == "Legal Career"
    assert suggestions[1].project == "BAE"


def test_follow_up_tomorrow_preserves_title_and_sets_high_priority():
    [suggestion] = parse_inbox_text(
        "follow up tomorrow with Marc",
        today=date(2026, 6, 29),
    )

    assert suggestion.title == "Follow up with Marc"
    assert suggestion.due_date == date(2026, 6, 30)
    assert suggestion.priority == "high"


def test_this_week_and_area_inference():
    [suggestion] = parse_inbox_text(
        "send Motherwell article this week",
        today=date(2026, 6, 29),
    )

    assert suggestion.title == "Send Motherwell article"
    assert suggestion.this_week is True
    assert suggestion.due_date is None
    assert suggestion.priority == "medium"
    assert suggestion.area == "Steelmen Dispatch"
    assert suggestion.project == "Steelmen Dispatch"


def test_weekday_date_uses_next_upcoming_instance():
    [suggestion] = parse_inbox_text(
        "review application Friday",
        today=date(2026, 6, 30),
    )

    assert suggestion.title == "Review application"
    assert suggestion.due_date == date(2026, 7, 3)
    assert suggestion.area == "Legal Career"


def test_camel_case_alias_matches_public_interface():
    assert parseInboxText("prepare CV")[0].title == "Prepare CV"


def test_parser_has_no_hosted_ai_client_dependency():
    text = open(inbox_parser.__file__).read().lower()
    for banned in ("anthropic", "openai", "import claude", "llm api"):
        assert banned not in text
