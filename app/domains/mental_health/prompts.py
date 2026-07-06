"""Rotating, state-aware reflection prompts for the evening review.

Deterministic: the prompt is picked by date so it rotates daily without
repetition fatigue, and the pool is chosen by today's recorded state (low
mood / high stress / good day / neutral). Prompts are CBT-informed — several
are thought-record openers — but written as plain questions, not clinical
worksheets.
"""

from __future__ import annotations

from datetime import date

LOW_MOOD_PROMPTS: tuple[str, ...] = (
    "Name one thing today that was genuinely neutral or okay, however small.",
    "What would you say to a friend who had the exact day you just had?",
    "Which thought today was a fact, and which was the mind's commentary on it?",
    "What did you still do today despite feeling low? That counts double.",
    "If today scored 3/10, what stopped it being 1/10?",
    "What is one kind, boring thing you can set up for tomorrow-you tonight?",
    "Low days distort memory toward the negative. List two things the filter left out.",
    "What did you need today that you didn't ask for?",
)

HIGH_STRESS_PROMPTS: tuple[str, ...] = (
    "Write the loudest thought from today, then write what a fair observer would add.",
    "Which of today's open loops is actually yours to carry? Name one that isn't.",
    "What is the most likely outcome of the thing you're bracing for — not the worst?",
    "If you could only solve one of today's problems tomorrow, which one moves the most?",
    "Where did the pressure come from today: the situation, or a rule about how you *should* handle it?",
    "What's the 10-minute version of the task you're avoiding?",
    "Name the feeling precisely (pressured? cornered? behind?). Precision shrinks it.",
    "What would 'good enough' have looked like today?",
)

GOOD_DAY_PROMPTS: tuple[str, ...] = (
    "What made today work? Be specific enough to repeat it.",
    "Which choice today do you want future-you to keep making?",
    "Who or what helped today — and did they know?",
    "What did you have energy for today that you usually don't? What preceded it?",
    "Bank the evidence: write one sentence proving today happened, for a harder day.",
    "What did you not do today that usually drags you down?",
)

NEUTRAL_PROMPTS: tuple[str, ...] = (
    "What took more energy today than it should have?",
    "One thing you learned, one thing you'd redo, one thing you're leaving here.",
    "What did you avoid today, and what was the story attached to it?",
    "Which moment today would you keep if you could only keep one?",
    "What's quietly going fine that you haven't acknowledged lately?",
    "If tomorrow copied today exactly, what one change would you order?",
    "What belief did today's evidence support — and what did it contradict?",
    "Where did your attention actually go today, versus where you planned it to go?",
)


def evening_prompt(day: date, mood: int | None = None, stress: int | None = None) -> str:
    """Deterministic prompt for the given day, biased by recorded state."""
    if mood is not None and mood <= 3:
        pool = LOW_MOOD_PROMPTS
    elif stress is not None and stress >= 8:
        pool = HIGH_STRESS_PROMPTS
    elif mood is not None and mood >= 8:
        pool = GOOD_DAY_PROMPTS
    else:
        pool = NEUTRAL_PROMPTS
    return pool[day.toordinal() % len(pool)]
