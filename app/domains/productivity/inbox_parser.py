"""Deterministic command-inbox parser for messy task text.

This module is intentionally local and rule-based. It uses splitting, keyword
matching, date phrase detection, and small scoring rules only. No AI API,
hosted model, paid parser, or external inference service is required.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import re
from uuid import uuid4


@dataclass(frozen=True)
class ParsedTaskSuggestion:
    id: str
    title: str
    area: str
    category: str
    priority: str
    due_date: date | None
    notes: str
    project: str
    today: bool
    this_week: bool
    confidence: float
    reason: str


FILLER_PATTERNS = [
    r"can you remind me to",
    r"please remind me to",
    r"remind me to",
    r"i have to",
    r"i need to",
    r"need to",
    r"remember to",
    r"should",
    r"please",
]

HIGH_PRIORITY = {
    "urgent",
    "overdue",
    "deadline",
    "chase",
    "follow up",
    "today",
    "asap",
    "must",
    "finalise",
}
MEDIUM_PRIORITY = {
    "need to",
    "should",
    "this week",
    "prepare",
    "review",
    "send",
    "finish",
}
LOW_PRIORITY = {
    "maybe",
    "idea",
    "someday",
    "explore",
    "consider",
    "eventually",
}

AREA_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "Steelmen Dispatch",
        (
            "steelmen dispatch",
            "motherwell",
            "article",
            "fanzine",
            "website",
            "alfred",
            "rosenborg",
            "spfl",
        ),
    ),
    (
        "Health & Fitness",
        (
            "gym",
            "run",
            "workout",
            "weight",
            "health",
            "sleep",
            "asthma",
            "football training",
        ),
    ),
    (
        "Finance",
        (
            "money",
            "credit card",
            "bill",
            "savings",
            "tax",
            "klarna",
            "loan",
            "budget",
            "payment",
        ),
    ),
    (
        "DPLP/University",
        (
            "dplp",
            "university",
            "diploma",
            "assignment",
            "exam",
            "tutorial",
        ),
    ),
    (
        "Legal Career",
        (
            "job",
            "interview",
            "cv",
            "application",
            "legal",
            "traineeship",
            "paralegal",
            "bae",
            "ashurst",
            "newsky",
        ),
    ),
    (
        "Coding Projects",
        (
            "repo",
            "code",
            "app",
            "claude",
            "codex",
            "github",
            "widget",
            "react",
            "wordpress",
        ),
    ),
    (
        "Creative Writing",
        (
            "book",
            "essay",
            "writing",
            "draft",
            "poem",
            "chapter",
        ),
    ),
]

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def parse_inbox_text(input_text: str, *, today: date | None = None) -> list[ParsedTaskSuggestion]:
    """Parse messy local text into editable task suggestions.

    The returned suggestions are not persisted. The caller owns any
    review-before-save flow.
    """

    base_date = today or date.today()
    suggestions: list[ParsedTaskSuggestion] = []
    seen: set[tuple[str, date | None]] = set()

    for raw in _split_candidates(input_text):
        cleaned = _clean_candidate(raw)
        if not cleaned:
            continue
        due_date, today_flag, this_week, date_reason = _detect_date(cleaned, base_date)
        title = _strip_date_phrases(cleaned)
        title = _remove_filler(title)
        title = _tidy_title(title)
        if len(title) < 2:
            continue

        key = (_normalise(title), due_date)
        if key in seen:
            continue
        seen.add(key)

        area, area_reason = _infer_area(cleaned)
        category, category_reason = _infer_category(cleaned, area)
        project, project_reason = _infer_project(cleaned, area)
        priority, priority_reason = _infer_priority(cleaned)
        notes = _build_notes(raw)
        confidence, confidence_reason = _confidence(
            has_date=bool(date_reason),
            area=area,
            priority=priority,
            title=title,
        )
        reason = "; ".join(
            part
            for part in [
                date_reason,
                area_reason,
                category_reason,
                project_reason,
                priority_reason,
                confidence_reason,
            ]
            if part
        )

        suggestions.append(
            ParsedTaskSuggestion(
                id=f"inbox-{uuid4().hex[:10]}",
                title=title,
                area=area,
                category=category,
                priority=priority,
                due_date=due_date,
                notes=notes,
                project=project,
                today=today_flag,
                this_week=this_week,
                confidence=confidence,
                reason=reason,
            )
        )

    return suggestions


# Camel-case alias so a future TypeScript/AI-backed implementation can expose
# the same public shape without changing callers that follow the product brief.
parseInboxText = parse_inbox_text


def _split_candidates(text: str) -> list[str]:
    prepared = text.replace("\r\n", "\n").replace("\r", "\n")
    prepared = re.sub(r"(?i)\b(and then|also)\b", "\n", prepared)
    prepared = re.sub(
        r"(?i)\b(can you remind me to|i have to|i need to|need to|remember to)\b",
        r"\n\1",
        prepared,
    )
    prepared = re.sub(r"[;,\n]+", "\n", prepared)
    parts: list[str] = []
    for line in prepared.splitlines():
        line = re.sub(r"^\s*(?:[-*•]+|\d+[.)]|\[[ xX]\])\s*", "", line).strip()
        if line:
            parts.append(line)
    return parts


def _clean_candidate(raw: str) -> str:
    text = raw.strip(" \t.-")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"(?i)^and\s+", "", text)
    return text.strip()


def _remove_filler(text: str) -> str:
    cleaned = text
    for pattern in FILLER_PATTERNS:
        cleaned = re.sub(rf"(?i)\b{pattern}\b", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip(" -")


def _detect_date(text: str, base_date: date) -> tuple[date | None, bool, bool, str]:
    lower = text.lower()
    if re.search(r"\btoday\b", lower):
        return base_date, True, False, "due today"
    if re.search(r"\btomorrow\b", lower):
        return base_date + timedelta(days=1), False, False, "due tomorrow"
    if re.search(r"\bthis week\b", lower):
        return None, False, True, "marked for this week"
    if re.search(r"\bnext week\b", lower):
        return base_date + timedelta(days=7), False, False, "due next week"

    for name, weekday in WEEKDAYS.items():
        if re.search(rf"\b{name}\b", lower):
            days_ahead = (weekday - base_date.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            return base_date + timedelta(days=days_ahead), False, False, f"due {name}"
    return None, False, False, ""


def _strip_date_phrases(text: str) -> str:
    stripped = text
    stripped = re.sub(r"(?i)\b(?:by|on|for|due)\s+(today|tomorrow|this week|next week)\b", " ", stripped)
    stripped = re.sub(r"(?i)\b(today|tomorrow|this week|next week)\b", " ", stripped)
    weekday_pattern = "|".join(WEEKDAYS)
    stripped = re.sub(rf"(?i)\b(?:by|on|for|due)\s+({weekday_pattern})\b", " ", stripped)
    stripped = re.sub(rf"(?i)\b({weekday_pattern})\b", " ", stripped)
    return re.sub(r"\s+", " ", stripped).strip(" -")


def _infer_priority(text: str) -> tuple[str, str]:
    lower = text.lower()
    high_hits = _keyword_hits(lower, HIGH_PRIORITY)
    medium_hits = _keyword_hits(lower, MEDIUM_PRIORITY)
    low_hits = _keyword_hits(lower, LOW_PRIORITY)

    if high_hits:
        return "high", f"priority high via {', '.join(high_hits)}"
    if medium_hits:
        return "medium", f"priority medium via {', '.join(medium_hits)}"
    if low_hits:
        return "low", f"priority low via {', '.join(low_hits)}"
    return "medium", "priority medium by default"


def _infer_area(text: str) -> tuple[str, str]:
    lower = text.lower()
    for area, keywords in AREA_RULES:
        hits = _keyword_hits(lower, set(keywords))
        if hits:
            return area, f"area {area} via {', '.join(hits[:2])}"
    return "Misc Review", "area Misc Review by fallback"


def _infer_category(text: str, area: str) -> tuple[str, str]:
    lower = text.lower()
    if _keyword_hits(lower, {"follow up", "chase"}):
        return "Follow-up", "category Follow-up"
    if _keyword_hits(lower, {"send", "message", "email"}):
        return "Comms", "category Comms"
    if area == "Legal Career":
        return "Career", "category Career"
    if area == "Health & Fitness":
        return "Health", "category Health"
    if area == "Finance":
        return "Finance", "category Finance"
    if area == "Coding Projects":
        return "Build", "category Build"
    if area in {"Steelmen Dispatch", "Creative Writing"}:
        return "Writing", "category Writing"
    if _keyword_hits(lower, {"prepare", "review", "finish", "finalise"}):
        return "Delivery", "category Delivery"
    return "Inbox", "category Inbox"


def _infer_project(text: str, area: str) -> tuple[str, str]:
    lower = text.lower()
    project_keywords = {
        "bae": "BAE",
        "ashurst": "Ashurst",
        "newsky": "NewSky",
        "dplp": "DPLP",
        "motherwell": "Steelmen Dispatch",
        "steelmen": "Steelmen Dispatch",
        "orion": "ORION",
        "wordpress": "WordPress",
        "github": "GitHub",
    }
    for keyword, project in project_keywords.items():
        if _contains_keyword(lower, keyword):
            return project, f"project {project}"
    if area == "Steelmen Dispatch":
        return "Steelmen Dispatch", "project Steelmen Dispatch"
    if area == "Coding Projects":
        return "Coding Projects", "project Coding Projects"
    return "", ""


def _build_notes(raw: str) -> str:
    return "\n".join(["Parsed locally by Command Inbox.", f"Original: {raw.strip()}"])


def _confidence(*, has_date: bool, area: str, priority: str, title: str) -> tuple[float, str]:
    score = 0.55
    if has_date:
        score += 0.15
    if area != "Misc Review":
        score += 0.15
    if priority != "medium":
        score += 0.05
    if len(title.split()) >= 3:
        score += 0.05
    score = min(score, 0.95)
    return round(score, 2), f"confidence {round(score, 2):.2f}"


def _keyword_hits(text: str, keywords: set[str]) -> list[str]:
    return [keyword for keyword in sorted(keywords) if _contains_keyword(text, keyword)]


def _contains_keyword(text: str, keyword: str) -> bool:
    pattern = r"\b" + re.escape(keyword.lower()).replace(r"\ ", r"\s+") + r"\b"
    return re.search(pattern, text) is not None


def _tidy_title(text: str) -> str:
    title = re.sub(r"\s+", " ", text).strip(" .:-")
    title = re.sub(r"(?i)^and\s+", "", title).strip()
    if not title:
        return ""
    return title[0].upper() + title[1:]


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
