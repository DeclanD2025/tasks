"""The homepage briefing layer (app/domains/briefing/).

The behaviours worth protecting are mostly refusals and reframings: what the
brief declines to claim when data is stale, and how it describes a backlog
without turning it into an accusation.

The scoring tests use literal task dicts so the logic is checkable by reading —
a ranking that silently shapes what someone works on every morning should not
require a database to reason about.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.database import session_scope
from app.db.models import BriefEvent, DailyBrief, Task
from app.domains.briefing import brief as brief_service
from app.domains.briefing import priorities as prio
from app.domains.briefing import quality as dq
from app.domains.briefing import review as review_mod

USER = 1
TODAY = date(2026, 7, 18)


def _task(**kw) -> dict:
    base = {
        "id": kw.pop("id", 1),
        "title": kw.pop("title", "A task"),
        "area": kw.pop("area", "Personal"),
        "priority": kw.pop("priority", "medium"),
        "status": "open",
        "due_date": None,
        "created_at": datetime(2026, 7, 1),
        "remote_created_at": None,
    }
    base.update(kw)
    return base


@pytest.fixture(autouse=True)
def _clean_briefs():
    yield
    with session_scope() as s:
        for model in (BriefEvent, DailyBrief):
            for row in s.scalars(select(model)).all():
                s.delete(row)
            s.flush()


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
def test_a_pinned_task_outranks_everything_without_competing_on_points():
    """Manual decisions must always win. A pinned task that had to beat the
    scorer on merit would sometimes lose, which defeats the point of pinning."""
    pinned = prio.score_task(_task(pinned_for=TODAY), today=TODAY)
    urgent = prio.score_task(
        _task(id=2, due_date=TODAY, priority="high", impact="high"), today=TODAY
    )
    assert pinned.pinned is True
    assert pinned.score > urgent.score
    assert pinned.as_dict()["selectedBy"] == "you"


def test_every_score_is_a_sum_of_named_explainable_components():
    """A score the operator cannot interrogate is a score they cannot correct."""
    scored = prio.score_task(
        _task(due_date=TODAY, next_action="Open the draft"), today=TODAY
    )
    assert scored.components
    assert scored.score == pytest.approx(sum(c.points for c in scored.components))
    for component in scored.components:
        assert component.label and component.detail


def test_the_priority_field_is_used_lightly_because_it_carries_no_signal():
    """273 of 288 open tasks are "medium". Weighting it heavily would rank at
    random, so being marked high must not outweigh an actual deadline."""
    marked_high = prio.score_task(_task(priority="high"), today=TODAY)
    due_today = prio.score_task(_task(id=2, due_date=TODAY), today=TODAY)
    assert due_today.score > marked_high.score


def test_overdue_pressure_is_capped_so_ancient_tasks_cannot_dominate():
    """Left uncapped the oldest task wins forever, and old usually means it
    deserves to be old."""
    three_weeks = prio.score_task(_task(due_date=TODAY - timedelta(days=21)), today=TODAY)
    six_months = prio.score_task(_task(id=2, due_date=TODAY - timedelta(days=180)), today=TODAY)
    assert six_months.score == pytest.approx(three_weeks.score)


def test_age_contributes_but_only_a_little():
    ancient = prio.score_task(
        _task(created_at=datetime(2025, 1, 1)), today=TODAY
    )
    age = [c for c in ancient.components if c.key == "age"]
    assert age and age[0].points <= prio._MAX_AGE_POINTS


def test_a_written_next_action_is_rewarded():
    """A task without a first step is a wish, and ranking it wastes the slot."""
    ready = prio.score_task(_task(next_action="Email the printer"), today=TODAY)
    vague = prio.score_task(_task(id=2), today=TODAY)
    assert ready.score > vague.score


def test_a_blocked_task_is_pushed_down_and_says_what_it_waits_on():
    blocked = prio.score_task(
        _task(due_date=TODAY, blocked=True, waiting_for="Struan's copy"), today=TODAY
    )
    reason = [c for c in blocked.components if c.key == "blocked"]
    assert reason and "Struan's copy" in reason[0].detail
    assert blocked.score < prio.score_task(_task(id=2, due_date=TODAY), today=TODAY).score


def test_repeatedly_deferred_tasks_sink():
    """Passed over four times means the task is wrong, not the day."""
    fresh = prio.score_task(_task(due_date=TODAY), today=TODAY)
    tired = prio.score_task(_task(id=2, due_date=TODAY, deferral_count=4), today=TODAY)
    assert tired.score < fresh.score


def test_deferred_and_archived_tasks_are_excluded_with_a_reason():
    deferred = prio.score_task(
        _task(defer_until=TODAY + timedelta(days=3)), today=TODAY
    )
    archived = prio.score_task(_task(id=2, archived_at=datetime.now()), today=TODAY)
    assert deferred.excluded.startswith("deferred until")
    assert archived.excluded == "archived"


def test_a_task_longer_than_the_time_left_is_penalised():
    quick = prio.score_task(
        _task(due_date=TODAY, estimate_minutes=20), today=TODAY, minutes_available=60
    )
    long = prio.score_task(
        _task(id=2, due_date=TODAY, estimate_minutes=180), today=TODAY, minutes_available=60
    )
    assert quick.score > long.score


def test_undated_tasks_stay_visible_at_low_weight():
    """Two thirds of the backlog is undated. Scoring it zero would make most of
    the list permanently unreachable."""
    scored = prio.score_task(_task(), today=TODAY)
    assert scored.score > 0


def test_the_headline_reason_is_one_thing_not_six():
    """A card listing every contributing factor has explained nothing."""
    scored = prio.score_task(
        _task(due_date=TODAY, priority="high", impact="high", next_action="Go"),
        today=TODAY,
    )
    assert scored.headline_reason() == "Due today."


# --------------------------------------------------------------------------- #
# Selection
# --------------------------------------------------------------------------- #
def _dispatch_backlog() -> list[dict]:
    """Approximates production: one project dominating the overdue pile."""
    tasks = [
        _task(id=i, title=f"Dispatch item {i}",
              area="Steelmen Dispatch Issue 4 / Production deadlines",
              due_date=TODAY - timedelta(days=10))
        for i in range(1, 12)
    ]
    tasks.append(_task(id=90, title="Book dentist", area="Personal",
                       due_date=TODAY - timedelta(days=2)))
    tasks.append(_task(id=91, title="Renew insurance", area="Home",
                       due_date=TODAY - timedelta(days=1)))
    return tasks


def test_selection_spreads_across_projects():
    """Three items from one deadline wave is one priority wearing three hats,
    and it crowds out everything else the operator has going on."""
    chosen = prio.select_priorities(_dispatch_backlog(), today=TODAY, limit=3)
    projects = {c.as_dict()["project"] for c in chosen}
    assert len(projects) == 3


def test_selection_never_returns_more_than_asked():
    chosen = prio.select_priorities(_dispatch_backlog(), today=TODAY, limit=3)
    assert len(chosen) == 3


def test_a_single_project_backlog_still_fills_the_slots():
    """Diversity is a preference, not a reason to show fewer priorities."""
    only_dispatch = [t for t in _dispatch_backlog() if "Dispatch" in t["area"]]
    chosen = prio.select_priorities(only_dispatch, today=TODAY, limit=3)
    assert len(chosen) == 3


def test_pinned_tasks_are_always_selected():
    tasks = _dispatch_backlog()
    tasks.append(_task(id=99, title="Pinned thing", area="Personal", pinned_for=TODAY))
    chosen = prio.select_priorities(tasks, today=TODAY, limit=3)
    assert 99 in [c.task["id"] for c in chosen]


def test_completed_tasks_are_never_selected():
    tasks = [_task(id=1, status="done", due_date=TODAY)]
    assert prio.select_priorities(tasks, today=TODAY) == []


# --------------------------------------------------------------------------- #
# Review reframing
# --------------------------------------------------------------------------- #
def test_a_dominant_project_is_named_instead_of_a_bare_total():
    """"95 tasks past due" describes someone failing at everything. The same
    data says one publication's schedule slipped."""
    result = review_mod.review_buckets(_dispatch_backlog(), today=TODAY)
    assert "Steelmen Dispatch Issue 4" in result["headline"]
    assert "one project's schedule slipped" in result["headline"]


def test_a_spread_backlog_is_not_blamed_on_one_project():
    tasks = [
        _task(id=1, area="Personal", due_date=TODAY - timedelta(days=2)),
        _task(id=2, area="Home", due_date=TODAY - timedelta(days=2)),
        _task(id=3, area="Work", due_date=TODAY - timedelta(days=2)),
    ]
    result = review_mod.review_buckets(tasks, today=TODAY)
    assert "spread across several areas" in result["headline"]


def test_rotted_habits_are_separated_from_real_tasks():
    """Morning journal dated three weeks ago is not an overdue task, it is a
    daily behaviour that decayed into permanent guilt."""
    tasks = [
        _task(id=1, title="Morning journal", due_date=TODAY - timedelta(days=20)),
        _task(id=2, title="Duolingo", due_date=TODAY - timedelta(days=20)),
        _task(id=3, title="Edit the feature", due_date=TODAY - timedelta(days=2)),
    ]
    buckets = {b["key"]: b for b in review_mod.review_buckets(tasks, today=TODAY)["buckets"]}
    assert buckets["habit_candidates"]["count"] == 2
    assert buckets["overdue"]["count"] == 1


def test_undated_tasks_get_their_own_bucket():
    tasks = [_task(id=i) for i in range(1, 6)]
    buckets = {b["key"]: b for b in review_mod.review_buckets(tasks, today=TODAY)["buckets"]}
    assert buckets["needs_date"]["count"] == 5


def test_long_dead_tasks_are_separated_from_merely_late_ones():
    tasks = [
        _task(id=1, title="Ancient", due_date=TODAY - timedelta(days=90)),
        _task(id=2, title="Recent", due_date=TODAY - timedelta(days=3)),
    ]
    buckets = {b["key"]: b for b in review_mod.review_buckets(tasks, today=TODAY)["buckets"]}
    assert buckets["stale"]["count"] == 1
    assert buckets["overdue"]["count"] == 1


def test_already_triaged_tasks_drop_out_of_review():
    tasks = [_task(id=1, review_status="keep", due_date=TODAY - timedelta(days=5))]
    result = review_mod.review_buckets(tasks, today=TODAY)
    assert all(b["count"] == 0 for b in result["buckets"])


def test_the_homepage_only_gets_a_few_examples_per_bucket():
    """The full clean-up belongs on the review screen, not the first screen."""
    tasks = [_task(id=i) for i in range(1, 20)]
    buckets = {b["key"]: b for b in review_mod.review_buckets(tasks, today=TODAY)["buckets"]}
    assert len(buckets["needs_date"]["examples"]) == 3


# --------------------------------------------------------------------------- #
# Data quality
# --------------------------------------------------------------------------- #
def test_quality_is_judged_per_domain_from_records():
    """Derived from records rather than DataSource.status, which in production
    flags both calendar connectors "mock" while holding 81 real events."""
    result = dq.assess(USER)
    assert set(result) == {"health", "tasks", "calendar", "training"}
    for source in result.values():
        assert source.trust in {"live", "stale", "empty"}


def test_a_stale_source_explains_itself_in_words():
    source = dq._judge("tasks", "Tasks", date.today() - timedelta(days=30), 10)
    assert source.trust == "stale"
    assert "30 days ago" in source.note
    assert source.usable is False


def test_an_empty_source_is_distinct_from_a_stale_one():
    """No data and old data are different problems with different fixes."""
    assert dq._judge("tasks", "Tasks", None, 0).trust == "empty"


def test_warnings_are_silent_when_everything_is_current():
    """A permanent row of green ticks is plumbing, and plumbing does not belong
    on the first screen."""
    fresh = {"health": dq._judge("health", "Health", date.today(), 5)}
    assert dq.warnings_from(fresh) == []


# --------------------------------------------------------------------------- #
# Brief composition
# --------------------------------------------------------------------------- #
def test_dayparts_split_the_day():
    assert brief_service.daypart_for(datetime(2026, 7, 18, 9)) == "morning"
    assert brief_service.daypart_for(datetime(2026, 7, 18, 14)) == "afternoon"
    assert brief_service.daypart_for(datetime(2026, 7, 18, 20)) == "evening"
    assert brief_service.daypart_for(datetime(2026, 7, 18, 23)) == "night"


def test_the_brief_generates_and_persists():
    payload = brief_service.generate(USER, force=True)
    assert payload["stateSummary"]
    assert payload["ruleVersion"] == prio.RULE_VERSION
    with session_scope() as s:
        stored = s.scalars(select(DailyBrief).where(DailyBrief.user_id == USER)).first()
    assert stored is not None
    assert stored.state_summary == payload["stateSummary"]


def test_generating_twice_reuses_the_stored_brief():
    """Regenerating on every load would change the next action under the
    operator mid-glance, and destroy the record of what was suggested."""
    first = brief_service.generate(USER, force=True)
    second = brief_service.generate(USER)
    assert first["stateSummary"] == second["stateSummary"]
    with session_scope() as s:
        assert len(s.scalars(select(DailyBrief).where(DailyBrief.user_id == USER)).all()) == 1


def test_the_brief_refuses_to_describe_recovery_without_current_health_data():
    stale = {
        "health": dq._judge("health", "Health data", date.today() - timedelta(days=30), 5),
    }
    summary, evidence = brief_service._state_summary(None, stale, "morning")
    assert "nothing to say about how you are recovering" in summary


def test_the_brief_carries_evidence_for_what_it_claims():
    """Every clause should trace to a value, so "why does it say that?" is
    answerable by opening the brief rather than by trusting it."""
    payload = brief_service.generate(USER, force=True)
    assert isinstance(payload["evidence"], dict)
    assert "sources" in payload


def test_confidence_falls_when_multiple_sources_are_stale():
    stale = {
        k: dq._judge(k, k, date.today() - timedelta(days=60), 1)
        for k in ("health", "tasks")
    }
    assert brief_service._confidence(stale, []) == "low"


def test_generating_logs_what_was_suggested():
    """The archive of suggestions is half the data; without it "are these any
    good?" is unanswerable forever.

    Creates its own task rather than relying on seed contents — the seeded test
    database has no tasks, so depending on it made this test pass or fail based
    on which database it happened to run against.
    """
    with session_scope() as s:
        s.add(Task(user_id=USER, title="Something to suggest", area="Personal",
                   status="open", due_date=date.today()))
    try:
        brief_service.generate(USER, force=True)
        with session_scope() as s:
            events = s.scalars(
                select(BriefEvent).where(BriefEvent.kind == "priority_generated")
            ).all()
        assert events
        assert events[0].subject == "Something to suggest"
        assert "score" in events[0].detail
    finally:
        # Events reference the task, so they have to go first — the FK is the
        # point (a logged suggestion should not outlive its subject silently).
        with session_scope() as s:
            for row in s.scalars(select(BriefEvent)).all():
                s.delete(row)
            s.flush()
            for row in s.scalars(
                select(Task).where(Task.title == "Something to suggest")
            ).all():
                s.delete(row)


def test_a_manual_edit_survives_and_does_not_overwrite_the_generated_text():
    brief_service.generate(USER, force=True)
    brief_service.edit_brief(USER, date.today(), focus="Rest today.")
    reloaded = brief_service._load(USER, date.today())
    assert reloaded["focus"] == "Rest today."
    assert reloaded["edited"] is True
    with session_scope() as s:
        row = s.scalars(select(DailyBrief).where(DailyBrief.user_id == USER)).first()
        assert row.focus != "Rest today.", "generated text must survive underneath"


def test_editing_an_unknown_field_is_refused():
    brief_service.generate(USER, force=True)
    with pytest.raises(ValueError, match="Cannot edit"):
        brief_service.edit_brief(USER, date.today(), priorities="nonsense")


def test_effectiveness_reports_counts_not_rates_on_thin_data():
    """One user over a short window cannot support a meaningful percentage."""
    brief_service.generate(USER, force=True)
    result = brief_service.effectiveness(USER, days=30)
    assert result["prioritiesGenerated"] >= 0
    assert "Counts, not rates" in result["note"]
