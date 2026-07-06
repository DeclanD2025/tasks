"""Stoic observability — a deterministic model of the path to *eudaimonia*.

The premise: you cannot measure "a good soul" directly, but Stoicism gives a
concrete framework whose components have measurable proxies in data ORION
already collects. Everything here is rule-based and statistical — NO LLM, no
network, fully local and reproducible.

The model
=========
Eudaimonia (flourishing) = living in agreement with nature and reason. We
operationalise it as the product of three measurable pillars:

1. The four cardinal VIRTUES (each 0..100), from behavioural proxies:
     - Wisdom (sophia)      : learning + deep work + reflective journaling
     - Justice (dikaiosyne) : attention given to others / community / fairness
     - Courage (andreia)    : facing hard things — training load, difficult tasks
     - Temperance           : restraint — spending discipline, sleep regularity

2. EQUANIMITY (ataraxia, 0..1): physiological calm + low volatility, from HRV,
   resting HR and sleep consistency.

3. PRACTICE consistency (0..1): the Stoic disciplines actually done — morning
   premeditation, evening review (Seneca), reflection streaks.

Plus two orienting instruments:
   - The DICHOTOMY OF CONTROL gauge: share of effort spent on what is "up to us"
     (Epictetus) vs what is not.
   - MEMENTO MORI: life-weeks elapsed — a gentle finitude prompt.

EUDAIMONIA INDEX = mean(virtues)/100 * equanimity * practice, scaled to 0..100.

Because real "journaling" / "mood" sources are not yet wired, those proxies fall
back to deterministic estimates derived from existing health/activity/finance
data (and a fixed seed), so the page is meaningful today and improves as real
Stoic-practice data is captured later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
from sqlalchemy import select

from app import services
from app.db.database import session_scope
from app.db.models import StoicEntry


# Birth date used only for the memento-mori life-weeks instrument. Override via
# a future Settings field; kept local and non-identifying.
ASSUMED_BIRTH_YEAR = 1995
ASSUMED_LIFE_EXPECTANCY_YEARS = 86  # a reference horizon, not a prediction


@dataclass
class Factor:
    """One transparent input to a score: what it measured and what it contributed.

    ``readout`` is the human-readable measured value (e.g. "deep work 3.1h/day").
    ``contribution`` is the points it added toward the 0..100 score.
    ``is_real`` flags whether this came from a real data source (vs unavailable).
    """

    label: str
    readout: str
    contribution: float
    weight: float
    is_real: bool = True


@dataclass
class Virtue:
    key: str
    name: str
    greek: str
    score: float | None        # 0..100, or None when there is no real signal
    note: str                  # one-line deterministic interpretation
    factors: list[Factor] = field(default_factory=list)
    coverage: float = 0.0      # 0..1 share of the score backed by real data

    @property
    def has_data(self) -> bool:
        return self.score is not None

    @property
    def display(self) -> str:
        return f"{self.score:.0f}" if self.score is not None else "—"


@dataclass
class Signal:
    """A 0..1 measured quantity that may be absent (no real source yet)."""

    value: float | None
    factors: list[Factor] = field(default_factory=list)
    coverage: float = 0.0

    @property
    def has_data(self) -> bool:
        return self.value is not None

    def or_zero(self) -> float:
        return self.value if self.value is not None else 0.0


@dataclass
class StoicPractice:
    label: str
    code: str
    done: bool
    streak: int                # consecutive days
    tracked: bool = False      # whether a real source (Apple Health) backs this
    detail: str = ""           # human-readable provenance, e.g. "9/14 days"


@dataclass
class StoicLogItem:
    id: int
    day: date
    virtue_focus: str
    control_pct: int
    reflected: bool
    served_others: bool
    faced_hard_thing: bool
    restrained_impulse: bool
    study_minutes: int
    reflection: str


@dataclass
class StoicSnapshot:
    title: str = "Stoic Observatory"
    subtitle: str = "The measured path to eudaimonia"
    eudaimonia_index: float | None = None    # 0..100, None if insufficient real data
    eudaimonia_factors: list[Factor] = field(default_factory=list)
    eudaimonia_trend: list[float] = field(default_factory=list)
    eudaimonia_coverage: float = 0.0         # 0..1 overall data backing
    virtues: list[Virtue] = field(default_factory=list)
    equanimity: Signal = field(default_factory=lambda: Signal(None))
    equanimity_trend: list[float] = field(default_factory=list)
    control: Signal = field(default_factory=lambda: Signal(None))
    practices: list[StoicPractice] = field(default_factory=list)
    practice_consistency: float | None = None  # 0..1, None if untracked
    practice_tracked: bool = False
    maxim: str = ""
    maxim_author: str = ""
    life_weeks_lived: int = 0
    life_weeks_total: int = 0
    reflections: list[dict] = field(default_factory=list)  # insight-style rows
    checkins: list[StoicLogItem] = field(default_factory=list)


# A small local table of Stoic maxims. Deterministic selection — no API.
_MAXIMS: list[tuple[str, str]] = [
    ("You have power over your mind — not outside events. Realise this, and you will find strength.",
     "Marcus Aurelius"),
    ("We suffer more often in imagination than in reality.", "Seneca"),
    ("It is not what happens to you, but how you react to it that matters.", "Epictetus"),
    ("Waste no more time arguing about what a good man should be. Be one.", "Marcus Aurelius"),
    ("Man is disturbed not by things, but by the views he takes of them.", "Epictetus"),
    ("He who fears death will never do anything worthy of a living man.", "Seneca"),
    ("The happiness of your life depends upon the quality of your thoughts.", "Marcus Aurelius"),
    ("No man is free who is not master of himself.", "Epictetus"),
    ("Luck is what happens when preparation meets opportunity.", "Seneca"),
    ("Confine yourself to the present.", "Marcus Aurelius"),
    ("First say to yourself what you would be; and then do what you have to do.", "Epictetus"),
    ("Difficulties show a person's character.", "Epictetus"),
]


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


# A virtue/signal is only reported when at least this share of its weight is
# backed by real (non-fabricated) data. Below it, we say NO DATA rather than
# invent a number.
MIN_COVERAGE = 0.30


def _fmt_hours(minutes: float) -> str:
    return f"{minutes / 60:.1f}h/day"


def _score_hits(entries: list[StoicLogItem], attr: str, days: int = 14) -> tuple[float, str]:
    recent = [e for e in entries if e.day >= date.today() - timedelta(days=days - 1)]
    if not recent:
        return 0.0, "no local check-ins"
    hits = sum(1 for e in recent if bool(getattr(e, attr)))
    return hits / days, f"{hits}/{days} days"


def _recent_entries(user_id: int, days: int = 30) -> list[StoicLogItem]:
    since = date.today() - timedelta(days=days)
    with session_scope() as s:
        rows = s.scalars(
            select(StoicEntry).where(StoicEntry.user_id == user_id)
            .where(StoicEntry.day >= since)
            .order_by(StoicEntry.day.desc())
        ).all()
        return [
            StoicLogItem(
                r.id,
                r.day,
                r.virtue_focus,
                r.control_pct,
                bool(r.reflected),
                bool(r.served_others),
                bool(r.faced_hard_thing),
                bool(r.restrained_impulse),
                r.study_minutes,
                r.reflection,
            )
            for r in rows
        ]


def upsert_today_entry(
    user_id: int,
    *,
    virtue_focus: str,
    control_pct: int,
    reflected: bool,
    served_others: bool,
    faced_hard_thing: bool,
    restrained_impulse: bool,
    study_minutes: int,
    reflection: str,
) -> None:
    today = date.today()
    with session_scope() as s:
        row = s.scalars(
            select(StoicEntry).where(StoicEntry.user_id == user_id, StoicEntry.day == today)
        ).first()
        if row is None:
            row = StoicEntry(user_id=user_id, day=today)
            s.add(row)
        row.virtue_focus = virtue_focus.strip() or "wisdom"
        row.control_pct = max(0, min(100, int(control_pct)))
        row.reflected = bool(reflected)
        row.served_others = bool(served_others)
        row.faced_hard_thing = bool(faced_hard_thing)
        row.restrained_impulse = bool(restrained_impulse)
        row.study_minutes = max(0, min(600, int(study_minutes)))
        row.reflection = reflection.strip()


# --------------------------------------------------------------------------- #
# Honest scoring helpers
# --------------------------------------------------------------------------- #
def _score_from_factors(factors: list[Factor]) -> tuple[float | None, float]:
    """Combine factors into a 0..100 score and a 0..1 coverage.

    Each factor contributes ``contribution`` (already weighted points) only if
    ``is_real``. Coverage is the share of total weight that was real. If coverage
    is below MIN_COVERAGE we return (None, coverage) — i.e. NO DATA.
    """
    total_weight = sum(f.weight for f in factors) or 1.0
    real_weight = sum(f.weight for f in factors if f.is_real)
    coverage = real_weight / total_weight
    if coverage < MIN_COVERAGE:
        return None, coverage
    # Re-normalise the real contributions to a full 0..100 scale so a partially
    # covered virtue is not unfairly capped.
    real_points = sum(f.contribution for f in factors if f.is_real)
    score = _clamp(real_points / real_weight) * 100
    return round(score, 1), coverage


# --------------------------------------------------------------------------- #
# Equanimity (ataraxia) — REAL: HRV + sleep regularity + mood (Apple Health)
# --------------------------------------------------------------------------- #
def _equanimity(user_id: int) -> tuple[Signal, list[float]]:
    hf = services.health_frame(user_id)
    mf = services.mood_frame(user_id)
    factors: list[Factor] = []
    trend: list[float] = []

    hrv = hf["hrv_ms"].dropna() if not hf.empty else None
    if hrv is not None and not hrv.empty:
        mean_hrv = float(hrv.tail(7).mean())
        hrv_unit = _clamp((mean_hrv - 30) / 50)
        factors.append(Factor("HRV (7d)", f"{mean_hrv:.0f} ms", hrv_unit * 0.45, 0.45, True))
        roll = hrv.rolling(3, min_periods=1).mean()
        trend = [_clamp((v - 30) / 50) for v in roll.tail(14)]
    else:
        factors.append(Factor("HRV (7d)", "no source", 0.0, 0.45, False))

    sleep = hf["sleep_minutes"].dropna() if not hf.empty else None
    if sleep is not None and len(sleep) >= 4:
        cv = sleep.tail(14).std() / (sleep.tail(14).mean() or 1)
        reg = _clamp(1.0 - cv * 2.5)
        factors.append(Factor("Sleep regularity", f"CV {cv:.0%}", reg * 0.30, 0.30, True))
    else:
        factors.append(Factor("Sleep regularity", "no source", 0.0, 0.30, False))

    # Mood: Apple Health State of Mind valence [-1,1] -> [0,1]. Inferred, not
    # self-reported in ORION.
    if not mf.empty:
        mean_mood = float(mf["mood"].tail(7).mean())
        mood_unit = _clamp((mean_mood + 1) / 2)
        factors.append(Factor("Mood (Apple Health)", f"valence {mean_mood:+.2f}",
                              mood_unit * 0.25, 0.25, True))
    else:
        factors.append(Factor("Mood (Apple Health)", "no State of Mind data", 0.0, 0.25, False))

    score, coverage = _score_from_factors(factors)
    value = (score / 100.0) if score is not None else None
    return Signal(value, factors, coverage), (trend or ([value] * 14 if value else []))


# --------------------------------------------------------------------------- #
# Cardinal virtues — REAL where a source exists, NO DATA otherwise
# --------------------------------------------------------------------------- #
def _virtues(user_id: int, entries: list[StoicLogItem]) -> list[Virtue]:
    af = services.activity_frame(user_id)
    hf = services.health_frame(user_id)
    ms = services.monthly_spending(user_id)
    has_af = not af.empty
    has_hf = not hf.empty

    virtues: list[Virtue] = []

    # --- Wisdom: deep work (real) [+ study source: not yet wired] ---
    wf: list[Factor] = []
    if has_af and af["deep_work_minutes"].notna().any():
        deep = float(af["deep_work_minutes"].tail(7).mean())
        wf.append(Factor("Deep work", _fmt_hours(deep), _clamp(deep / 240) * 0.8, 0.8, True))
    else:
        wf.append(Factor("Deep work", "no source", 0.0, 0.8, False))
    study_entries = [e for e in entries if e.study_minutes > 0]
    if study_entries:
        study = float(np.mean([e.study_minutes for e in study_entries[:14]]))
        wf.append(Factor("Study check-ins", _fmt_hours(study), _clamp(study / 120) * 0.2, 0.2, True))
    else:
        wf.append(Factor("Study check-ins", "no local entries", 0.0, 0.2, False))
    w_score, w_cov = _score_from_factors(wf)
    virtues.append(Virtue(
        "wisdom", "Wisdom", "sophia", w_score,
        _virtue_note(w_score, "Sustained focus deepens the rational faculty.",
                     "Reason is a muscle — schedule deliberate study."),
        wf, w_cov,
    ))

    # --- Courage: training load (real) [+ hard-task source: not yet wired] ---
    cf: list[Factor] = []
    if has_af and af["training_load"].notna().any():
        load = float(af["training_load"].tail(7).mean())
        cf.append(Factor("Training load", f"{load:.0f}/100", _clamp(load / 100) * 0.7, 0.7, True))
    else:
        cf.append(Factor("Training load", "no source", 0.0, 0.7, False))
    hard_unit, hard_readout = _score_hits(entries, "faced_hard_thing")
    cf.append(Factor("Hard things faced", hard_readout, hard_unit * 0.3, 0.3, bool(entries)))
    c_score, c_cov = _score_from_factors(cf)
    virtues.append(Virtue(
        "courage", "Courage", "andreia", c_score,
        _virtue_note(c_score, "You are meeting difficulty rather than avoiding it.",
                     "Seek the harder path; that is where virtue grows."),
        cf, c_cov,
    ))

    # --- Temperance: spending discipline (real) + sleep regularity (real) ---
    tf: list[Factor] = []
    if len(ms) >= 2:
        prev = ms["spend"].iloc[-2] or 1
        disc = _clamp(1.0 - (ms["spend"].iloc[-1] - prev) / prev)
        delta = (ms["spend"].iloc[-1] - prev) / prev
        tf.append(Factor("Spending discipline", f"{delta:+.0%} vs last mo", disc * 0.35, 0.35, True))
    else:
        tf.append(Factor("Spending discipline", "no source", 0.0, 0.35, False))
    if has_hf and hf["sleep_minutes"].dropna().shape[0] >= 4:
        s = hf["sleep_minutes"].dropna()
        sleep_reg = _clamp(1.0 - (s.tail(14).std() / (s.tail(14).mean() or 1)) * 2.5)
        tf.append(Factor("Sleep regularity", f"{sleep_reg:.0%}", sleep_reg * 0.35, 0.35, True))
    else:
        tf.append(Factor("Sleep regularity", "no source", 0.0, 0.35, False))
    restraint_unit, restraint_readout = _score_hits(entries, "restrained_impulse")
    tf.append(Factor("Restrained impulse", restraint_readout, restraint_unit * 0.30, 0.30,
                     bool(entries)))
    t_score, t_cov = _score_from_factors(tf)
    virtues.append(Virtue(
        "temperance", "Temperance", "sophrosyne", t_score,
        _virtue_note(t_score, "Appetites are within bounds; restraint is holding.",
                     "Small indulgences accumulate — restore the boundaries."),
        tf, t_cov,
    ))

    # --- Justice: attention to others — local check-ins until calendar people-time lands ---
    served_unit, served_readout = _score_hits(entries, "served_others")
    jf = [
        Factor("Served-others check-in", served_readout, served_unit * 0.7, 0.7,
               bool(entries)),
        Factor("People-time source", "calendar source not wired", 0.0, 0.3, False),
    ]
    j_score, j_cov = _score_from_factors(jf)  # -> None, low coverage
    virtues.append(Virtue(
        "justice", "Justice", "dikaiosyne", j_score,
        _virtue_note(j_score, "Justice has a lived signal: attention given outward.",
                     "Look for one concrete service to another person today."),
        jf, j_cov,
    ))

    # keep the canonical order: wisdom, justice, courage, temperance
    order = {"wisdom": 0, "justice": 1, "courage": 2, "temperance": 3}
    virtues.sort(key=lambda v: order[v.key])
    return virtues


def _virtue_note(score: float | None, high: str, low: str) -> str:
    if score is None:
        return "No measurable signal yet — this virtue has no wired data source."
    return high if score >= 55 else low


# --------------------------------------------------------------------------- #
# Reflective practice — ingested from Apple Health Mindfulness (no double-entry)
# --------------------------------------------------------------------------- #
# A day "counts" as a practice day if at least this many mindful minutes logged.
PRACTICE_MIN_MINUTES = 3


def _practices(
    user_id: int,
    entries: list[StoicLogItem],
) -> tuple[list[StoicPractice], float | None, bool]:
    """Reflective-practice signal, ingested rather than re-asked.

    The Stoic app (and Mindfulness/Calm/etc.) write Mindfulness sessions to Apple
    Health. We read those: a day with >= PRACTICE_MIN_MINUTES mindful minutes is
    a practice day. This avoids any double-entry — ORION never re-asks you to log
    a ritual you already did in Stoic. If there is no mindful data, practice is
    honestly untracked.
    """
    pf = services.practice_frame(user_id, days=30)
    local_reflections = {e.day for e in entries if e.reflected}
    if pf.empty and not local_reflections:
        return ([StoicPractice("Reflective Practice", "STO-PRA", False, 0, tracked=False)], None,
                False)

    by_day = {} if pf.empty else {
        row["day"]: float(row["mindful_minutes"]) for _, row in pf.iterrows()
    }
    today = date.today()
    for entry_day in local_reflections:
        by_day[entry_day] = max(by_day.get(entry_day, 0.0), float(PRACTICE_MIN_MINUTES))
    # Current streak: consecutive days up to today meeting the threshold.
    streak = 0
    d = today
    while by_day.get(d, 0.0) >= PRACTICE_MIN_MINUTES:
        streak += 1
        d = d - timedelta(days=1)
    # Consistency: share of the last 14 days with a qualifying session.
    last14 = [today - timedelta(days=i) for i in range(14)]
    hits = sum(1 for day in last14 if by_day.get(day, 0.0) >= PRACTICE_MIN_MINUTES)
    consistency = hits / 14
    done_today = by_day.get(today, 0.0) >= PRACTICE_MIN_MINUTES

    total_min = sum(by_day.values())
    source = "Apple Health + local check-ins" if not pf.empty and local_reflections else (
        "Apple Health Mindfulness" if not pf.empty else "local check-ins"
    )
    practice = StoicPractice("Reflective Practice", "STO-PRA", done_today, streak, tracked=True)
    practice.detail = f"{hits}/14 days · {total_min:.0f} mindful min ({source})"
    return [practice], consistency, True


# --------------------------------------------------------------------------- #
# Dichotomy of control — REAL: controllable effort vs external volatility
# --------------------------------------------------------------------------- #
def _control(user_id: int, entries: list[StoicLogItem]) -> Signal:
    af = services.activity_frame(user_id)
    factors: list[Factor] = []
    controllable = 0.0
    real = False
    if not af.empty and (af["deep_work_minutes"].notna().any() or af["active_minutes"].notna().any()):
        controllable = float(af["deep_work_minutes"].tail(7).fillna(0).sum()
                             + af["active_minutes"].tail(7).fillna(0).sum())
        real = True

    nw = services.net_worth_series(user_id)
    external = 1.0
    if not nw.empty and len(nw) > 2:
        external = float(np.std(np.diff(nw["value"].to_numpy()))) or 1.0

    local = [e.control_pct / 100 for e in entries[:14]]
    if not real and local:
        ratio = float(np.mean(local))
        factors.append(Factor("Local control check-in", f"{ratio * 100:.0f}%", ratio, 1.0, True))
        return Signal(ratio, factors, 1.0)
    if not real:
        factors.append(Factor("Controllable effort", "no source", 0.0, 1.0, False))
        return Signal(None, factors, 0.0)

    raw = controllable / (controllable + external * 4 + 1)
    ratio = _clamp(0.5 + 0.5 * raw)  # honest blend, no random nudge
    if local:
        ratio = _clamp((ratio * 0.55) + (float(np.mean(local)) * 0.45))
    factors.append(Factor("Deliberate effort (7d)", f"{controllable / 60:.1f}h",
                          ratio, 0.7, True))
    factors.append(Factor("External volatility", f"σ {external:,.0f}", 0.0, 0.3, True))
    if local:
        factors.append(Factor("Local control check-in", f"{float(np.mean(local)) * 100:.0f}%",
                              float(np.mean(local)), 0.45, True))
    return Signal(ratio, factors, 1.0)


def _life_weeks() -> tuple[int, int]:
    today = date.today()
    born = date(ASSUMED_BIRTH_YEAR, 1, 1)
    lived = max(0, (today - born).days // 7)
    total = ASSUMED_LIFE_EXPECTANCY_YEARS * 52
    return lived, total


def _reflections(
    virtues: list[Virtue],
    equ: Signal,
    control: Signal,
    entries: list[StoicLogItem],
) -> list[dict]:
    out: list[dict] = []
    measured = [v for v in virtues if v.has_data]
    unmeasured = [v for v in virtues if not v.has_data]

    if measured:
        weakest = min(measured, key=lambda v: v.score)
        strongest = max(measured, key=lambda v: v.score)
        out.append({
            "domain": "stoic", "severity": "info",
            "title": f"{weakest.name} is your current frontier ({weakest.score:.0f}/100).",
            "body": weakest.note,
        })
        out.append({
            "domain": "stoic", "severity": "positive",
            "title": f"{strongest.name} is well-tended ({strongest.score:.0f}/100).",
            "body": "Guard this strength without letting it become pride.",
        })
    if unmeasured:
        names = ", ".join(v.name for v in unmeasured)
        out.append({
            "domain": "stoic", "severity": "warning",
            "title": f"No signal for: {names}.",
            "body": "These virtues have no wired data source yet, so they are reported as "
                    "NO DATA rather than estimated. Wire a source or use the daily check-in.",
        })
    if equ.has_data and equ.value < 0.45:
        out.append({
            "domain": "stoic", "severity": "warning",
            "title": "Equanimity is low this week.",
            "body": "Much disturbance is in judgement, not in things. Return to the present.",
        })
    if control.has_data:
        if control.value < 0.5:
            out.append({
                "domain": "stoic", "severity": "warning",
                "title": "Energy is leaking toward what is not up to you.",
                "body": "Spend yourself only on the controllable — the discipline of desire.",
            })
        else:
            out.append({
                "domain": "stoic", "severity": "positive",
                "title": "Your effort is well-aimed at the controllable.",
                "body": "This is the heart of the discipline of desire.",
            })
    for entry in [e for e in entries if e.reflection.strip()][:3]:
        out.append({
            "domain": "stoic", "severity": "info",
            "title": f"{entry.day.strftime('%d %b')} reflection · {entry.virtue_focus.title()}",
            "body": entry.reflection,
        })
    return out


def _eudaimonia_trend(index_now: float, equ_trend: list[float]) -> list[float]:
    """Trajectory derived from the REAL equanimity trend, scaled to the index —
    no random walk. If equanimity has no trend we return a flat line."""
    if not equ_trend:
        return [index_now] * 14
    base = float(np.mean(equ_trend)) or 1.0
    return [float(_clamp(index_now * (v / base), 0, 100)) for v in equ_trend[-14:]]


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def get_stoic_snapshot(user_id: int | None) -> StoicSnapshot:
    snap = StoicSnapshot()
    if user_id is None:
        return snap

    entries = _recent_entries(user_id)
    virtues = _virtues(user_id, entries)
    equ, equ_trend = _equanimity(user_id)
    practices, consistency, tracked = _practices(user_id, entries)
    control = _control(user_id, entries)

    # Eudaimonia index = mean(measured virtues) modulated by equanimity and (if
    # tracked) practice. Built ONLY from real signals; None if too little data.
    measured = [v for v in virtues if v.has_data]
    eud_factors: list[Factor] = []
    index: float | None = None
    coverage = 0.0
    if measured:
        mean_virtue = float(np.mean([v.score for v in measured])) / 100.0
        eud_factors.append(Factor(
            "Cardinal virtues", f"{len(measured)}/4 measured, mean {mean_virtue * 100:.0f}",
            mean_virtue, 0.6, True,
        ))
        equ_mult = (0.4 + 0.6 * equ.value) if equ.has_data else 0.7
        eud_factors.append(Factor(
            "Equanimity", f"{equ.value * 100:.0f}%" if equ.has_data else "no source",
            equ_mult, 0.25, equ.has_data,
        ))
        if tracked and consistency is not None:
            prac_mult = 0.5 + 0.5 * consistency
            eud_factors.append(Factor("Practice consistency", f"{consistency * 100:.0f}%",
                                      prac_mult, 0.15, True))
        else:
            prac_mult = 1.0  # don't penalise for an unwired source
            eud_factors.append(Factor("Practice consistency", "untracked", prac_mult, 0.15, False))
        index = round(_clamp(mean_virtue * equ_mult * prac_mult) * 100, 1)
        # coverage = share of virtues measured, tempered by equanimity availability
        coverage = (len(measured) / 4) * (0.8 + 0.2 * (1 if equ.has_data else 0))

    lived, total = _life_weeks()
    # Maxim: deterministic daily rotation by day-of-year (stable, no per-user seed)
    maxim_idx = date.today().timetuple().tm_yday % len(_MAXIMS)

    snap.virtues = virtues
    snap.equanimity = equ
    snap.equanimity_trend = equ_trend
    snap.practices = practices
    snap.practice_consistency = consistency
    snap.practice_tracked = tracked
    snap.control = control
    snap.eudaimonia_index = index
    snap.eudaimonia_factors = eud_factors
    snap.eudaimonia_coverage = round(coverage, 2)
    snap.eudaimonia_trend = _eudaimonia_trend(index if index is not None else 0.0, equ_trend)
    snap.maxim, snap.maxim_author = _MAXIMS[maxim_idx]
    snap.life_weeks_lived = lived
    snap.life_weeks_total = total
    snap.reflections = _reflections(virtues, equ, control, entries)
    snap.checkins = entries
    return snap
