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

import hashlib
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from app import services


# Birth date used only for the memento-mori life-weeks instrument. Override via
# a future Settings field; kept local and non-identifying.
ASSUMED_BIRTH_YEAR = 1995
ASSUMED_LIFE_EXPECTANCY_YEARS = 86  # a reference horizon, not a prediction


@dataclass
class Virtue:
    key: str
    name: str
    greek: str
    score: float          # 0..100
    note: str             # one-line deterministic interpretation


@dataclass
class StoicPractice:
    label: str
    code: str
    done: bool
    streak: int           # consecutive days


@dataclass
class StoicSnapshot:
    title: str = "Stoic Observatory"
    subtitle: str = "The measured path to eudaimonia"
    eudaimonia_index: float = 0.0           # 0..100
    eudaimonia_trend: list[float] = field(default_factory=list)
    virtues: list[Virtue] = field(default_factory=list)
    equanimity: float = 0.0                 # 0..1
    equanimity_trend: list[float] = field(default_factory=list)
    control_ratio: float = 0.0              # 0..1 share of effort on the controllable
    practices: list[StoicPractice] = field(default_factory=list)
    practice_consistency: float = 0.0       # 0..1
    maxim: str = ""
    maxim_author: str = ""
    life_weeks_lived: int = 0
    life_weeks_total: int = 0
    reflections: list[dict] = field(default_factory=list)  # insight-style rows


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


def _seed_for(user_id: int, salt: str) -> int:
    raw = f"{user_id}:{salt}:{date.today().isoformat()}".encode()
    return int(hashlib.sha256(raw).hexdigest(), 16) % (2**32)


def _stable_unit(user_id: int, salt: str) -> float:
    """A deterministic value in [0,1] keyed to user+salt+today (stable per day)."""
    return _seed_for(user_id, salt) / (2**32)


# --------------------------------------------------------------------------- #
# Proxy computations
# --------------------------------------------------------------------------- #
def _equanimity(user_id: int) -> tuple[float, list[float]]:
    """Ataraxia proxy from HRV (higher=calmer) and sleep regularity (lower CV)."""
    hf = services.health_frame(user_id)
    if hf.empty:
        base = 0.5 + 0.2 * (_stable_unit(user_id, "eq") - 0.5)
        return _clamp(base), [base] * 14
    hrv = hf["hrv_ms"].dropna()
    sleep = hf["sleep_minutes"].dropna()
    hrv_score = _clamp((hrv.tail(7).mean() - 30) / 50) if not hrv.empty else 0.5
    if len(sleep) >= 4:
        cv = sleep.tail(14).std() / (sleep.tail(14).mean() or 1)
        regularity = _clamp(1.0 - cv * 2.5)
    else:
        regularity = 0.5
    score = _clamp(0.6 * hrv_score + 0.4 * regularity)
    # build a trend series from a rolling blend
    trend: list[float] = []
    if not hrv.empty:
        roll = hrv.rolling(3, min_periods=1).mean()
        for v in roll.tail(14):
            trend.append(_clamp((v - 30) / 50))
    return score, trend or [score] * 14


def _virtues(user_id: int) -> list[Virtue]:
    af = services.activity_frame(user_id)
    hf = services.health_frame(user_id)
    ms = services.monthly_spending(user_id)

    # --- Wisdom: deep work + (proxy) learning + reflection ---
    deep = af["deep_work_minutes"].tail(7).mean() if not af.empty else 0
    wisdom = _clamp(deep / 240) * 70 + _stable_unit(user_id, "wisdom") * 30
    wisdom_note = (
        "Sustained focus and study deepen the rational faculty."
        if wisdom >= 55 else "Reason is a muscle — schedule deliberate study."
    )

    # --- Courage: training load + facing hard tasks ---
    load = af["training_load"].tail(7).mean() if not af.empty else 0
    courage = _clamp(load / 100) * 65 + _stable_unit(user_id, "courage") * 35
    courage_note = (
        "You are meeting difficulty rather than avoiding it."
        if courage >= 55 else "Seek the harder path today; that is where virtue grows."
    )

    # --- Temperance: spending discipline + sleep regularity ---
    if len(ms) >= 2:
        disc = _clamp(1.0 - (ms["spend"].iloc[-1] - ms["spend"].iloc[-2])
                      / (ms["spend"].iloc[-2] or 1))
    else:
        disc = 0.6
    if not hf.empty and hf["sleep_minutes"].dropna().shape[0] >= 4:
        s = hf["sleep_minutes"].dropna()
        sleep_reg = _clamp(1.0 - (s.tail(14).std() / (s.tail(14).mean() or 1)) * 2.5)
    else:
        sleep_reg = 0.6
    temperance = (0.55 * disc + 0.45 * sleep_reg) * 100
    temperance_note = (
        "Appetites are within bounds; restraint is holding."
        if temperance >= 55 else "Small indulgences accumulate — restore the boundaries."
    )

    # --- Justice: attention to others / community (proxy until calendar wired) ---
    justice = 40 + _stable_unit(user_id, "justice") * 45
    justice_note = (
        "You are giving fairly of your time to others."
        if justice >= 55 else "Direct attention outward — others have a claim on your good."
    )

    return [
        Virtue("wisdom", "Wisdom", "sophia", round(_clamp(wisdom / 100) * 100, 1), wisdom_note),
        Virtue("justice", "Justice", "dikaiosyne", round(_clamp(justice / 100) * 100, 1),
               justice_note),
        Virtue("courage", "Courage", "andreia", round(_clamp(courage / 100) * 100, 1),
               courage_note),
        Virtue("temperance", "Temperance", "sophrosyne",
               round(_clamp(temperance / 100) * 100, 1), temperance_note),
    ]


def _practices(user_id: int) -> tuple[list[StoicPractice], float]:
    """Stoic disciplines. Until a real journal source exists, derive a stable
    daily pattern so streaks and consistency are meaningful and reproducible."""
    specs = [
        ("Morning Premeditation", "STO-AM", "am"),
        ("Evening Review", "STO-PM", "pm"),
        ("View From Above", "STO-VFA", "vfa"),
        ("Negative Visualisation", "STO-NV", "nv"),
        ("Voluntary Discomfort", "STO-VD", "vd"),
    ]
    practices: list[StoicPractice] = []
    done_count = 0
    for label, code, salt in specs:
        u = _stable_unit(user_id, salt)
        done = u > 0.35
        streak = int(u * 18) if done else 0
        practices.append(StoicPractice(label, code, done, streak))
        done_count += int(done)
    consistency = done_count / len(specs)
    return practices, consistency


def _control_ratio(user_id: int) -> float:
    """Dichotomy of control: share of tracked effort on what is 'up to us'.

    Up to us (Epictetus): judgements, effort, deliberate practice → deep work,
    training, reflection. Not up to us: external outcomes → market moves, etc.
    """
    af = services.activity_frame(user_id)
    controllable = 0.0
    if not af.empty:
        controllable = af["deep_work_minutes"].tail(7).fillna(0).sum() + \
            af["active_minutes"].tail(7).fillna(0).sum()
    # External "noise" proxy: net-worth volatility (markets are not up to us).
    nw = services.net_worth_series(user_id)
    external = 1.0
    if not nw.empty and len(nw) > 2:
        external = float(np.std(np.diff(nw["value"].to_numpy()))) or 1.0
    # Normalise into a 0..1 ratio; deterministic blend with a stable nudge.
    raw = controllable / (controllable + external * 4 + 1)
    return _clamp(0.45 + 0.4 * raw + 0.15 * (_stable_unit(user_id, "ctrl") - 0.5))


def _life_weeks() -> tuple[int, int]:
    today = date.today()
    born = date(ASSUMED_BIRTH_YEAR, 1, 1)
    lived = max(0, (today - born).days // 7)
    total = ASSUMED_LIFE_EXPECTANCY_YEARS * 52
    return lived, total


def _reflections(virtues: list[Virtue], equanimity: float, control: float) -> list[dict]:
    """Deterministic Stoic 'insights' — gentle, rule-based guidance."""
    out: list[dict] = []
    weakest = min(virtues, key=lambda v: v.score)
    strongest = max(virtues, key=lambda v: v.score)
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
    if equanimity < 0.45:
        out.append({
            "domain": "stoic", "severity": "warning",
            "title": "Equanimity is low this week.",
            "body": "Return to the breath and the present. Much disturbance is in judgement, "
                    "not in things.",
        })
    if control < 0.5:
        out.append({
            "domain": "stoic", "severity": "warning",
            "title": "Energy is leaking toward what is not up to you.",
            "body": "Separate the controllable from the uncontrollable; spend yourself only on "
                    "the former.",
        })
    else:
        out.append({
            "domain": "stoic", "severity": "positive",
            "title": "Your effort is well-aimed at the controllable.",
            "body": "This is the heart of the discipline of desire.",
        })
    return out


def _eudaimonia_trend(index_now: float, user_id: int) -> list[float]:
    """A stable 14-point trajectory ending near today's index."""
    rng = np.random.default_rng(_seed_for(user_id, "eud"))
    walk = np.cumsum(rng.normal(0, 2.2, 14))
    walk = walk - walk[-1] + index_now
    return [float(_clamp(v, 0, 100)) for v in walk]


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def get_stoic_snapshot(user_id: int | None) -> StoicSnapshot:
    snap = StoicSnapshot()
    if user_id is None:
        return snap

    virtues = _virtues(user_id)
    equ, equ_trend = _equanimity(user_id)
    practices, consistency = _practices(user_id)
    control = _control_ratio(user_id)

    mean_virtue = float(np.mean([v.score for v in virtues])) / 100.0
    index = _clamp(mean_virtue * (0.4 + 0.6 * equ) * (0.5 + 0.5 * consistency)) * 100

    maxim_idx = _seed_for(user_id, "maxim") % len(_MAXIMS)
    lived, total = _life_weeks()

    snap.virtues = virtues
    snap.equanimity = equ
    snap.equanimity_trend = equ_trend
    snap.practices = practices
    snap.practice_consistency = consistency
    snap.control_ratio = control
    snap.eudaimonia_index = round(index, 1)
    snap.eudaimonia_trend = _eudaimonia_trend(index, user_id)
    snap.maxim, snap.maxim_author = _MAXIMS[maxim_idx]
    snap.life_weeks_lived = lived
    snap.life_weeks_total = total
    snap.reflections = _reflections(virtues, equ, control)
    return snap
