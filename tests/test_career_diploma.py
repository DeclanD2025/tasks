from __future__ import annotations

from app import services
from app.domains.career import career_service as career
from app.domains.diploma import diploma_service as diploma
from app.domains.stoic import stoic_service as stoic


def _uid() -> int:
    return services.get_default_user_id()


# --- Career matrices -------------------------------------------------------- #
def test_career_matrices_default_to_neutral():
    snap = career.get_snapshot(_uid())
    # All factors default to 50 → both headline scores land at 50.
    assert snap.jeopardy.value == 50.0
    assert snap.resilience.value == 50.0
    assert snap.jeopardy.higher_is_good is False
    assert snap.resilience.higher_is_good is True


def test_protective_factors_lower_jeopardy():
    uid = _uid()
    # Max out every protective factor; zero the inverted (automation) one.
    for key, _label, _w in career.JEOPARDY_FACTORS:
        career.set_matrix_factor(uid, "jeopardy", key,
                                 0 if key in career.JEOPARDY_INVERTED else 100)
    snap = career.get_snapshot(uid)
    assert snap.jeopardy.value <= 5.0          # well-protected => low risk
    assert snap.jeopardy.band == "SECURE"


def test_automation_exposure_raises_jeopardy():
    uid = _uid()
    # Strong on everything protective, but high automation exposure.
    for key, _label, _w in career.JEOPARDY_FACTORS:
        career.set_matrix_factor(uid, "jeopardy", key, 100)
    high = career.get_snapshot(uid).jeopardy.value
    career.set_matrix_factor(uid, "jeopardy", "automation_exposure", 0)
    low = career.get_snapshot(uid).jeopardy.value
    # Lowering exposure (0) reduces risk vs. high exposure (100).
    assert low < high


def test_resilience_blends_buffers():
    uid = _uid()
    for key, _label, _w in career.RESILIENCE_FACTORS:
        career.set_matrix_factor(uid, "resilience", key, 100)
    snap = career.get_snapshot(uid)
    assert snap.resilience.value >= 95.0
    assert snap.resilience.band == "STRONG"


def test_career_goal_crud_roundtrip():
    uid = _uid()
    before = len(career.list_goals(uid))
    gid = career.add_goal(uid, "Ship v1")
    career.update_goal(gid, progress=100)
    goals = {g.id: g for g in career.list_goals(uid)}
    assert goals[gid].progress == 100
    career.delete_goal(gid)
    assert len(career.list_goals(uid)) == before


def test_career_planning_notes_and_traineeships_roundtrip():
    uid = _uid()
    note = career.add_note(uid, "Decision log", "Prioritise traineeships.", "decision")
    step = career.add_plan_step(uid, "Refresh CV", horizon="now")
    trn = career.add_traineeship(uid, "Data traineeship", "City College")

    career.update_note(note, body="CV first, applications second.", tag="plan")
    career.update_plan_step(step, progress=40, status="active", notes="Draft ready")
    career.update_traineeship(trn, status="applied", progress=55, notes="Submitted")

    snap = career.get_snapshot(uid)
    notes = {n.id: n for n in snap.notes}
    steps = {p.id: p for p in snap.plan_steps}
    traineeships = {t.id: t for t in snap.traineeships}
    assert notes[note].tag == "plan"
    assert "CV first" in notes[note].body
    assert steps[step].progress == 40
    assert steps[step].status == "active"
    assert traineeships[trn].status == "applied"
    assert traineeships[trn].progress == 55

    career.delete_note(note)
    career.delete_plan_step(step)
    career.delete_traineeship(trn)


def test_stoic_local_checkin_produces_real_signal():
    uid = _uid()
    stoic.upsert_today_entry(
        uid,
        virtue_focus="justice",
        control_pct=80,
        reflected=True,
        served_others=True,
        faced_hard_thing=True,
        restrained_impulse=True,
        study_minutes=45,
        reflection="Chose the useful thing over the easy thing.",
    )
    snap = stoic.get_stoic_snapshot(uid)
    assert snap.checkins
    assert snap.practice_tracked is True
    assert snap.control.has_data is True
    assert any(v.key == "justice" and v.has_data for v in snap.virtues)


# --- Diploma derivations ---------------------------------------------------- #
def test_weighted_average_only_counts_completed_graded_modules():
    uid = _uid()
    m1 = diploma.add_module(uid, "Module A", credits=20)
    m2 = diploma.add_module(uid, "Module B", credits=20)
    diploma.update_module(m1, grade=80.0, status="done")
    diploma.update_module(m2, grade=60.0, status="ongoing")  # not counted yet
    snap = diploma.get_snapshot(uid)
    assert snap.weighted_average == 80.0  # only the done+graded one
    diploma.update_module(m2, status="done")
    snap2 = diploma.get_snapshot(uid)
    assert snap2.weighted_average == 70.0  # equal credits/weight → mean
    diploma.delete_module(m1)
    diploma.delete_module(m2)


def test_progress_tracks_credits_earned():
    uid = _uid()
    diploma.update_program(uid, credits_required=100)
    m = diploma.add_module(uid, "Big module", credits=25)
    diploma.update_module(m, status="done", grade=55.0)
    snap = diploma.get_snapshot(uid)
    assert snap.credits_earned >= 25
    assert snap.progress_pct >= 25.0
    diploma.delete_module(m)


def test_preparedness_uses_status_not_time():
    uid = _uid()
    a = diploma.add_assessment(uid, "Essay", "assignment")
    e = diploma.add_assessment(uid, "Exam", "exam")
    diploma.update_assessment(a, status="in_progress")  # → 50
    diploma.update_assessment(e, readiness=70, status="revising")  # → 70
    snap = diploma.get_snapshot(uid)
    assert snap.prepared_pct == 60.0  # mean(50, 70)
    assert snap.open_assessment_count == 2
    # Submitting the essay removes it from "open".
    diploma.update_assessment(a, status="submitted")
    snap2 = diploma.get_snapshot(uid)
    assert snap2.open_assessment_count == 1
    diploma.delete_assessment(a)
    diploma.delete_assessment(e)
