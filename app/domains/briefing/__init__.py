"""The homepage briefing layer.

Composes ORION's data into one opinionated daily brief rather than exposing
every metric. See ``docs/homepage/01-audit.md`` for why the design is shaped
the way it is — most of it follows from three facts about the real data: the
task priority field is 95% one value, the task mirror is weeks stale, and the
connector registry mis-reports which sources are real.

- ``quality``    — freshness derived from records, never from connector claims.
- ``priorities`` — transparent, component-wise task scoring.
- ``review``     — turns a backlog into triage buckets.
- ``brief``      — assembles and persists the daily brief.
"""

from app.domains.briefing import brief, priorities, quality, review  # noqa: F401

__all__ = ["brief", "priorities", "quality", "review"]
