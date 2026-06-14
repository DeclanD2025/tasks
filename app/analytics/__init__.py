"""Deterministic analytics & insight generation.

CRITICAL: ORION's intelligence is rule-based and statistical only. No hosted
LLM (Claude, OpenAI, etc.) is ever called at runtime. Every insight here is
reproducible from the data alone.
"""

from app.analytics.engine import generate_insights  # noqa: F401
