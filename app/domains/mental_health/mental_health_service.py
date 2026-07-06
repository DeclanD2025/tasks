"""Local mental health support tools.

These helpers are deterministic self-reflection aids, not diagnosis or therapy.
They combine common unhelpful-thinking categories, ACT psychological-flexibility
prompts, and short nervous-system regulation practices.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class ThinkingTrap:
    key: str
    label: str
    description: str
    markers: tuple[str, ...]
    reframe_prompt: str
    act_move: str


@dataclass(frozen=True)
class ACTProcess:
    key: str
    label: str
    prompt: str


@dataclass(frozen=True)
class RegulationMethod:
    key: str
    label: str
    when_to_use: str
    steps: tuple[str, ...]
    mechanism: str


@dataclass(frozen=True)
class TrapHit:
    key: str
    label: str
    score: int
    description: str
    reframe_prompt: str
    act_move: str


@dataclass(frozen=True)
class ReflectionResult:
    trap_hits: tuple[TrapHit, ...]
    act_prompts: tuple[ACTProcess, ...]
    regulation: RegulationMethod
    next_action_prompt: str
    safety_note: str


THINKING_TRAPS: tuple[ThinkingTrap, ...] = (
    ThinkingTrap(
        "all_or_nothing",
        "All-or-nothing thinking",
        "The mind is turning a complex situation into total success or total failure.",
        ("always", "never", "completely", "totally", "ruined", "perfect", "failure"),
        "What would a 60 percent true version of this thought sound like?",
        "Defusion: say 'I am noticing an all-or-nothing story' before acting.",
    ),
    ThinkingTrap(
        "catastrophising",
        "Catastrophising",
        "The mind is jumping to the worst credible or non-credible outcome.",
        ("disaster", "catastrophe", "over", "can't cope", "cannot cope", "terrible", "awful"),
        "What is the most likely next step, not the worst possible ending?",
        "Present moment: find the next useful action inside the next 10 minutes.",
    ),
    ThinkingTrap(
        "mind_reading",
        "Mind-reading",
        "The mind is treating another person's private thoughts as known facts.",
        ("they think", "she thinks", "he thinks", "everyone thinks", "they hate", "judging me"),
        "What evidence would I need before treating this as fact?",
        "Values: choose the kind of person you want to be before you know their view.",
    ),
    ThinkingTrap(
        "fortune_telling",
        "Fortune-telling",
        "The mind is predicting the future with more certainty than the evidence allows.",
        ("will go wrong", "won't work", "will fail", "no point", "nothing will", "it'll fail"),
        "What is one small experiment that could test this prediction?",
        "Committed action: run the smallest values-based experiment.",
    ),
    ThinkingTrap(
        "should_statements",
        "Should statements",
        "The mind is using rigid rules that can intensify shame or pressure.",
        ("should", "must", "have to", "supposed to", "need to be"),
        "If this came from care rather than pressure, how would it be phrased?",
        "Acceptance: make room for discomfort while loosening the rule.",
    ),
    ThinkingTrap(
        "emotional_reasoning",
        "Emotional reasoning",
        "A strong feeling is being treated as proof that the thought is true.",
        ("i feel like", "feels like", "because i feel", "i'm anxious so", "i am anxious so"),
        "What can the feeling tell me without making it the judge?",
        "Self-as-context: notice the feeling as an event you are having.",
    ),
    ThinkingTrap(
        "mental_filter",
        "Mental filter",
        "Attention is narrowing onto threat, flaw, or loss while excluding other data.",
        ("only", "nothing good", "all bad", "one thing", "can't see anything"),
        "What data would a fair observer include alongside the difficult part?",
        "Present moment: widen attention to include three neutral facts.",
    ),
    ThinkingTrap(
        "personalisation",
        "Personalisation",
        "The mind is assigning too much responsibility to you for a wider situation.",
        ("my fault", "because of me", "i caused", "i made them", "blame me"),
        "What other causes, constraints, or people are part of this system?",
        "Values: take your share of responsibility, not the whole universe.",
    ),
)

ACT_PROCESSES: tuple[ACTProcess, ...] = (
    ACTProcess(
        "present_moment",
        "Contact the present moment",
        "Name five things that are true right now, without arguing with the thought.",
    ),
    ACTProcess(
        "defusion",
        "Cognitive defusion",
        "Put 'I am having the thought that...' in front of the thought and read it again.",
    ),
    ACTProcess(
        "acceptance",
        "Acceptance",
        "Ask: can I make room for this feeling for 60 seconds without obeying it?",
    ),
    ACTProcess(
        "self_as_context",
        "Self-as-context",
        "Notice: there is a part of me observing this thought, and that part is not the thought.",
    ),
    ACTProcess(
        "values",
        "Values",
        "Choose the value this situation asks for: care, courage, honesty, steadiness, learning.",
    ),
    ACTProcess(
        "committed_action",
        "Committed action",
        "Pick the smallest action that moves toward that value in the next 10 minutes.",
    ),
)

REGULATION_METHODS: tuple[RegulationMethod, ...] = (
    RegulationMethod(
        "physiological_sigh",
        "Physiological sigh",
        "High arousal, panic, or threat spikes.",
        (
            "Take a steady inhale through the nose.",
            "Before exhaling, take a second small top-up inhale.",
            "Exhale slowly through the mouth.",
            "Repeat 3 to 5 cycles, then breathe normally.",
        ),
        "Longer exhalation and respiratory reset can help downshift arousal.",
    ),
    RegulationMethod(
        "paced_breathing",
        "Paced breathing",
        "Stress, anger, rumination, or getting ready for sleep.",
        (
            "Inhale gently for 4 counts.",
            "Exhale gently for 6 counts.",
            "Keep the breath comfortable, not forced.",
            "Continue for 3 minutes.",
        ),
        "Slow breathing can support parasympathetic regulation and attention control.",
    ),
    RegulationMethod(
        "orienting_grounding",
        "Orienting and grounding",
        "Overwhelm, dissociation, or feeling pulled into mental replay.",
        (
            "Turn your head slowly and name five visible objects.",
            "Feel both feet or another contact point.",
            "Name three sounds.",
            "Describe one safe or neutral thing in the room.",
        ),
        "Sensory orienting moves attention from abstract threat loops to current context.",
    ),
    RegulationMethod(
        "urge_surfing",
        "Urge surfing",
        "Impulses, avoidance, checking, scrolling, or reassurance seeking.",
        (
            "Rate the urge from 0 to 10.",
            "Locate it in the body and describe its shape or temperature.",
            "Watch it for 90 seconds like a wave.",
            "Choose the next values-based action after the wave changes.",
        ),
        "Interoceptive attention can separate urge intensity from automatic behaviour.",
    ),
)

_HIGH_AROUSAL = re.compile(r"\b(panic|panicking|overwhelmed|spiral|racing|terror|urgent)\b")
_AVOIDANCE = re.compile(r"\b(avoid|avoiding|procrastinate|procrastinating|escape|scroll)\b")


def build_reflection(text: str) -> ReflectionResult:
    """Analyse a thought capture and return prompts for the UI."""
    normalised = " ".join(text.lower().split())
    hits = _trap_hits(normalised)
    regulation = _choose_regulation(normalised, hits)
    prompts = _act_prompts_for(hits)
    next_action = _next_action_prompt(hits)
    return ReflectionResult(
        trap_hits=tuple(hits),
        act_prompts=tuple(prompts),
        regulation=regulation,
        next_action_prompt=next_action,
        safety_note=(
            "If you might hurt yourself or someone else, treat this as urgent: "
            "contact local emergency services or a crisis support line now."
        ),
    )


def _trap_hits(text: str) -> list[TrapHit]:
    hits: list[TrapHit] = []
    for trap in THINKING_TRAPS:
        score = sum(1 for marker in trap.markers if marker in text)
        if score:
            hits.append(
                TrapHit(
                    key=trap.key,
                    label=trap.label,
                    score=score,
                    description=trap.description,
                    reframe_prompt=trap.reframe_prompt,
                    act_move=trap.act_move,
                )
            )
    return sorted(hits, key=lambda hit: (-hit.score, hit.label))[:4]


def _act_prompts_for(hits: list[TrapHit]) -> list[ACTProcess]:
    if not hits:
        return [ACT_PROCESSES[0], ACT_PROCESSES[1], ACT_PROCESSES[4], ACT_PROCESSES[5]]
    keys = {"defusion", "present_moment", "values", "committed_action"}
    if any(hit.key in {"should_statements", "emotional_reasoning"} for hit in hits):
        keys.add("acceptance")
        keys.add("self_as_context")
    return [process for process in ACT_PROCESSES if process.key in keys]


def _choose_regulation(text: str, hits: list[TrapHit]) -> RegulationMethod:
    if _HIGH_AROUSAL.search(text):
        return _method("physiological_sigh")
    if _AVOIDANCE.search(text):
        return _method("urge_surfing")
    if any(hit.key in {"catastrophising", "fortune_telling"} for hit in hits):
        return _method("paced_breathing")
    return _method("orienting_grounding")


def _method(key: str) -> RegulationMethod:
    return next(method for method in REGULATION_METHODS if method.key == key)


def _next_action_prompt(hits: list[TrapHit]) -> str:
    if not hits:
        return "Write one value-led action you can take in the next 10 minutes."
    primary = hits[0]
    return (
        f"Primary pattern: {primary.label}. Write one action that follows your values "
        "even if this thought comes along for the ride."
    )
