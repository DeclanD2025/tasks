"""ORION ORM models (SQLAlchemy 2.0 declarative).

The schema deliberately distinguishes the five data layers ORION operates on:

  1. Raw imported data      -> RawImport
  2. Normalised records     -> Transaction, (future per-domain normalised tables)
  3. Daily snapshots        -> BalanceSnapshot, HealthMetricDaily, ActivityMetricDaily,
                               ProjectMetricDaily
  4. Derived metrics        -> the *Daily snapshot tables double as derived metric
                               stores for the MVP; richer derived tables can be added
                               per-domain without migration churn.
  5. Insights               -> Insight

Everything is keyed to a User so the model is multi-profile ready, even though
the MVP runs a single local profile.

Design notes:
  * UTC timestamps everywhere (``datetime`` stored as UTC).
  * Monetary values are stored in minor units (integer pence/cents) to avoid
    float drift; a ``currency`` column travels with them.
  * ``extra`` JSON columns give each table a forward-compatible escape hatch so
    new integrations rarely require migrations.
"""

from __future__ import annotations

import enum
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base for all ORION models."""


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class Domain(str, enum.Enum):
    finance = "finance"
    health = "health"
    productivity = "productivity"
    creative = "creative"
    calendar = "calendar"
    tasks = "tasks"
    learning = "learning"
    football = "football"
    projects = "projects"


class SourceStatus(str, enum.Enum):
    disconnected = "disconnected"
    connected = "connected"
    error = "error"
    mock = "mock"


class InsightSeverity(str, enum.Enum):
    info = "info"
    positive = "positive"
    warning = "warning"
    critical = "critical"


class JobStatus(str, enum.Enum):
    running = "running"
    success = "success"
    failed = "failed"


class HealthStatus(str, enum.Enum):
    """User-set wellbeing state — the 'sickness protocol' status.

    ``active``  — systems normal.
    ``injured`` — systems normal; overall health is not impacted (a physical
                  injury, not an illness). Page stays blue; badge only.
    ``illness`` — unwell. Page accent shifts toward red and ORION prompts for a
                  daily symptom entry.
    """

    active = "active"
    injured = "injured"
    illness = "illness"


class SymptomSeverity(str, enum.Enum):
    mild = "mild"
    moderate = "moderate"
    severe = "severe"


# --------------------------------------------------------------------------- #
# Identity
# --------------------------------------------------------------------------- #
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120), default="Operator")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # NOTE: no password hash here in the MVP — the local unlock gate lives in
    # core.security. Add a hashed credential column when multi-user/OAuth lands.

    accounts: Mapped[list["Account"]] = relationship(back_populates="user")
    projects: Mapped[list["Project"]] = relationship(back_populates="user")


# --------------------------------------------------------------------------- #
# Sources & raw layer
# --------------------------------------------------------------------------- #
class DataSource(Base):
    """A configured integration (e.g. Trading 212, Apple Health)."""

    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    key: Mapped[str] = mapped_column(String(64), index=True)  # connector key
    name: Mapped[str] = mapped_column(String(120))
    domain: Mapped[Domain] = mapped_column(Enum(Domain))
    status: Mapped[SourceStatus] = mapped_column(
        Enum(SourceStatus), default=SourceStatus.mock
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # TODO(security): store tokens in the OS keychain (keyring), not the DB.
    extra: Mapped[dict] = mapped_column(JSON, default=dict)

    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_source_user_key"),)


class RawImport(Base):
    """Layer 1: untouched payloads exactly as received from a source."""

    __tablename__ = "raw_imports"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    # IMPORTANT: do not log this payload in production (may contain PII).
    processed: Mapped[bool] = mapped_column(default=False)


# --------------------------------------------------------------------------- #
# Finance — normalised + snapshots
# --------------------------------------------------------------------------- #
class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_sources.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(40))  # current | savings | investment | crypto
    currency: Mapped[str] = mapped_column(String(3), default="GBP")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)

    user: Mapped["User"] = relationship(back_populates="accounts")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="account")
    balances: Mapped[list["BalanceSnapshot"]] = relationship(back_populates="account")


class Transaction(Base):
    """Layer 2: a normalised money movement."""

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    booked_at: Mapped[date] = mapped_column(Date, index=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger)  # signed; minor units
    currency: Mapped[str] = mapped_column(String(3), default="GBP")
    category: Mapped[str] = mapped_column(String(64), default="uncategorised")
    description: Mapped[str] = mapped_column(String(255), default="")
    extra: Mapped[dict] = mapped_column(JSON, default=dict)

    account: Mapped["Account"] = relationship(back_populates="transactions")


class BalanceSnapshot(Base):
    """Layer 3: an account balance on a given day."""

    __tablename__ = "balance_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    balance_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default="GBP")

    account: Mapped["Account"] = relationship(back_populates="balances")

    __table_args__ = (
        UniqueConstraint("account_id", "snapshot_date", name="uq_balance_acct_date"),
    )


# --------------------------------------------------------------------------- #
# Health & activity — daily snapshots / derived metrics
# --------------------------------------------------------------------------- #
class HealthMetricDaily(Base):
    """Layer 3/4: one row per user per day of health metrics."""

    __tablename__ = "health_metrics_daily"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    sleep_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hrv_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    resting_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)

    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_health_user_day"),)


class HealthStatusLog(Base):
    """Sickness-protocol status history: one row per day the status changed.

    The current status is the most recent row by ``effective_from``. Keeping a
    log (rather than a single field) lets the symptom log show how long an
    illness ran and how vitals tracked it.
    """

    __tablename__ = "health_status_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[HealthStatus] = mapped_column(
        Enum(HealthStatus), default=HealthStatus.active
    )
    effective_from: Mapped[date] = mapped_column(Date, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)  # e.g. injury detail
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "effective_from", name="uq_status_user_day"),
    )


class SymptomEntry(Base):
    """One daily symptom log entry recorded while status is 'illness'."""

    __tablename__ = "symptom_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    severity: Mapped[SymptomSeverity] = mapped_column(
        Enum(SymptomSeverity), default=SymptomSeverity.mild
    )
    symptoms: Mapped[list] = mapped_column(JSON, default=list)  # checklist keys
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_symptom_user_day"),)


class ActivityMetricDaily(Base):
    """Layer 3/4: daily training / movement / productivity activity."""

    __tablename__ = "activity_metrics_daily"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    steps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # NOT the source of truth for training load, and null in practice. The
    # `training_load` metric is computed live from workout heart-rate data as
    # Edwards TRIMP (`derived.get_strain_days`), because a stored daily figure
    # would go stale the moment a workout was backfilled or corrected. Kept as
    # a column only so an importer that has a vendor-supplied load has
    # somewhere to put it; read `derived` instead.
    training_load: Mapped[float | None] = mapped_column(Float, nullable=True)
    deep_work_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)

    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_activity_user_day"),)


# --------------------------------------------------------------------------- #
# Projects
# --------------------------------------------------------------------------- #
class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(40), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped["User"] = relationship(back_populates="projects")
    metrics: Mapped[list["ProjectMetricDaily"]] = relationship(back_populates="project")


class ProjectMetricDaily(Base):
    __tablename__ = "project_metrics_daily"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    commits: Mapped[int] = mapped_column(Integer, default=0)
    words_written: Mapped[int] = mapped_column(Integer, default=0)
    tasks_done: Mapped[int] = mapped_column(Integer, default=0)
    momentum: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0..100

    project: Mapped["Project"] = relationship(back_populates="metrics")

    __table_args__ = (
        UniqueConstraint("project_id", "day", name="uq_projmetric_proj_day"),
    )


# --------------------------------------------------------------------------- #
# Insights — layer 5
# --------------------------------------------------------------------------- #
class Insight(Base):
    """Layer 5: a deterministic, rule/statistics-based finding.

    Generated entirely by `app.analytics` — NO LLM is involved at runtime.
    """

    __tablename__ = "insights"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    domain: Mapped[Domain] = mapped_column(Enum(Domain), index=True)
    severity: Mapped[InsightSeverity] = mapped_column(
        Enum(InsightSeverity), default=InsightSeverity.info
    )
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text, default="")
    rule_key: Mapped[str] = mapped_column(String(80))  # which rule produced it
    metric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


# --------------------------------------------------------------------------- #
# Scheduler bookkeeping
# --------------------------------------------------------------------------- #
class ScheduledJobRun(Base):
    __tablename__ = "scheduled_job_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_key: Mapped[str] = mapped_column(String(80), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.running)
    detail: Mapped[str] = mapped_column(Text, default="")


# --------------------------------------------------------------------------- #
# Web client write bookkeeping
# --------------------------------------------------------------------------- #
class ClientMutation(Base):
    """Receipt for client-generated write ids.

    Offline-capable web forms may replay the same POST after a flaky network
    transition. Keeping a tiny receipt table lets the server make those replays
    idempotent without adding client-specific columns to every domain table.
    """

    __tablename__ = "client_mutations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    mutation_id: Mapped[str] = mapped_column(String(96), index=True)
    action: Mapped[str] = mapped_column(String(120), default="")
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "mutation_id", name="uq_client_mutation_user_id"),
    )


# --------------------------------------------------------------------------- #
# Device sync bookkeeping
# --------------------------------------------------------------------------- #
class SyncDevice(Base):
    """A local ORION install participating in CloudKit sync."""

    __tablename__ = "sync_devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    platform: Mapped[str] = mapped_column(String(40), default="macos-desktop")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)


class SyncEntity(Base):
    """Stable CloudKit identity for one row in a local domain table."""

    __tablename__ = "sync_entities"

    id: Mapped[int] = mapped_column(primary_key=True)
    table_name: Mapped[str] = mapped_column(String(80), index=True)
    local_id: Mapped[int] = mapped_column(Integer, index=True)
    record_type: Mapped[str] = mapped_column(String(80), index=True)
    record_name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    source_device_id: Mapped[str] = mapped_column(String(36), index=True)
    cloudkit_change_tag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    conflict_policy: Mapped[str] = mapped_column(String(40), default="last_write_wins")
    payload_hash: Mapped[str] = mapped_column(String(64), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_pushed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_pulled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("table_name", "local_id", name="uq_sync_entity_local_row"),
    )


class SyncOutbox(Base):
    """Local queue of CloudKit mutations awaiting the signed Swift helper."""

    __tablename__ = "sync_outbox"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int | None] = mapped_column(
        ForeignKey("sync_entities.id"), nullable=True, index=True
    )
    record_type: Mapped[str] = mapped_column(String(80), index=True)
    record_name: Mapped[str] = mapped_column(String(64), index=True)
    operation: Mapped[str] = mapped_column(String(16), default="upsert")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class SyncCheckpoint(Base):
    """CloudKit server-change-token storage per private database zone."""

    __tablename__ = "sync_checkpoints"

    id: Mapped[int] = mapped_column(primary_key=True)
    database_scope: Mapped[str] = mapped_column(String(16), default="private")
    zone_name: Mapped[str] = mapped_column(String(80), default="orion-main")
    server_change_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)

    __table_args__ = (
        UniqueConstraint("database_scope", "zone_name", name="uq_sync_checkpoint_zone"),
    )


# --------------------------------------------------------------------------- #
# Fitness — a local, hand-editable training planner (no external integration)
# --------------------------------------------------------------------------- #
class FitnessPlan(Base):
    """A training block: name, purpose, focus, start date and length.

    Multiple plans can exist per user; exactly one is ``is_active`` (the block
    the calendar and dashboards centre on). ``focus`` biases the block toward
    strength / cardio / hybrid; ``purpose`` and ``goal`` capture intent and the
    measurable target so a plan reads as a plan, not just a date range.
    """

    __tablename__ = "fitness_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    block_name: Mapped[str] = mapped_column(String(120), default="Training Block")
    purpose: Mapped[str] = mapped_column(String(120), default="")  # e.g. "Build base"
    focus: Mapped[str] = mapped_column(String(16), default="hybrid")  # strength|cardio|hybrid
    goal: Mapped[str] = mapped_column(Text, default="")  # measurable target
    start_date: Mapped[date] = mapped_column(Date, default=utcnow)
    weeks: Mapped[int] = mapped_column(Integer, default=6)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class FitnessSession(Base):
    """A single planned session dropped onto a calendar day."""

    __tablename__ = "fitness_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    session_type: Mapped[str] = mapped_column(String(40))   # e.g. "ZONE 2 CARDIO"
    label: Mapped[str] = mapped_column(String(60), default="")  # optional override
    color: Mapped[str] = mapped_column(String(9), default="#2ee6ff")
    notes: Mapped[str] = mapped_column(Text, default="")
    completed: Mapped[bool] = mapped_column(default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)  # multiple per day
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Workout(Base):
    """A completed activity imported or entered locally.

    ``FitnessSession`` is the plan; ``Workout`` is what actually happened and
    can be matched to personal routes.
    """

    __tablename__ = "workouts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    source: Mapped[str] = mapped_column(String(80), default="manual")
    source_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    title: Mapped[str] = mapped_column(String(160), default="")
    sport_type: Mapped[str] = mapped_column(String(24), default="run")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    moving_time_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    distance_meters: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_heart_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_heart_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    elevation_gain_meters: Mapped[float | None] = mapped_column(Float, nullable=True)
    route_geometry: Mapped[list] = mapped_column(JSON, default=list)
    splits: Mapped[list] = mapped_column(JSON, default=list)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "source", "source_id", name="uq_workout_source"),
    )


class WorkoutSessionLog(Base):
    """A manually logged strength/cardio session with exercise-set children.

    ``Workout`` above mirrors imported Apple Health activities. This table is
    the fast local tracker: push/pull/legs/etc., completion state, notes and an
    effort rating. It intentionally stays compact so the UI can be quick rather
    than a full spreadsheet clone.
    """

    __tablename__ = "workout_session_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    title: Mapped[str] = mapped_column(String(160), default="Workout")
    category: Mapped[str] = mapped_column(String(24), default="custom")
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    completed: Mapped[bool] = mapped_column(default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    source_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("workout_session_logs.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ExerciseSet(Base):
    """One exercise-set line inside a workout session."""

    __tablename__ = "exercise_sets"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("workout_session_logs.id"), index=True)
    exercise_name: Mapped[str] = mapped_column(String(120))
    set_number: Mapped[int] = mapped_column(Integer, default=1)
    reps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    rpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# --------------------------------------------------------------------------- #
# Strength training — active workout tracker
# --------------------------------------------------------------------------- #
class StrengthExercise(Base):
    """Seeded or custom strength exercise metadata.

    ``family_slug`` is what makes variants tractable. Barbell bench, paused
    bench and close-grip bench are three distinct exercises — comparing their
    loads directly would be dishonest — but they answer the same question about
    horizontal pressing strength. Analytics can therefore roll up at four
    levels: exact exercise, family, movement pattern, muscle group.

    A string slug rather than a self-FK on purpose: seed data can declare its
    family without ID juggling, and an exercise archived years later does not
    orphan its variants.
    """

    __tablename__ = "strength_exercises"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    #: Operator's own label. Falls back to ``name`` when blank — renaming must
    #: never orphan history, so the canonical name is kept either way.
    display_name: Mapped[str] = mapped_column(String(160), default="")
    #: Search synonyms ("OHP", "military press"). Improves the picker without
    #: creating duplicate exercises that would split an exercise's history.
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    family_slug: Mapped[str] = mapped_column(String(120), default="", index=True)
    primary_muscle: Mapped[str] = mapped_column(String(32), index=True)
    secondary_muscles: Mapped[list] = mapped_column(JSON, default=list)
    equipment: Mapped[str] = mapped_column(String(40), index=True)
    movement_pattern: Mapped[str] = mapped_column(String(40), default="", index=True)
    category: Mapped[str] = mapped_column(String(32), default="strength")
    #: True for multi-joint work. Drives the indirect-volume weighting.
    is_compound: Mapped[bool] = mapped_column(default=False)
    unilateral: Mapped[bool] = mapped_column(default=False)
    laterality: Mapped[str] = mapped_column(String(24), default="bilateral")
    #: True when the recorded weight is *per implement* and both limbs are
    #: loaded at once — a dumbbell press logged as "22 kg" moves 44 kg. Every
    #: tracker records the number on one dumbbell, so without this flag the
    #: whole dumbbell half of a training log reads at half its real volume.
    #: False for single-implement work (goblet squat, kettlebell swing) and for
    #: unilateral work, where the sides are counted through reps instead.
    weight_is_per_limb: Mapped[bool] = mapped_column(default=False)
    load_type: Mapped[str] = mapped_column(String(24), default="external", index=True)
    measurement: Mapped[str] = mapped_column(String(16), default="reps")
    default_unit: Mapped[str] = mapped_column(String(8), default="kg")
    #: Smallest load step available for this exercise — 2.5 kg on a barbell,
    #: 5 kg on a stack, 2 kg between dumbbells. Progression proposes real
    #: numbers with this, instead of a load the gym cannot make.
    increment_kg: Mapped[float] = mapped_column(Float, default=2.5)
    bar_weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    instructions: Mapped[str] = mapped_column(Text, default="")
    setup_notes: Mapped[str] = mapped_column(Text, default="")
    rom_notes: Mapped[str] = mapped_column(Text, default="")
    #: Per-exercise tracking switches (track_rpe, track_rir, track_tempo…).
    tracking_config: Mapped[dict] = mapped_column(JSON, default=dict)
    default_sets: Mapped[int] = mapped_column(Integer, default=3)
    default_reps: Mapped[int] = mapped_column(Integer, default=8)
    notes: Mapped[str] = mapped_column(Text, default="")
    is_custom: Mapped[bool] = mapped_column(default=False)
    favorite: Mapped[bool] = mapped_column(default=False)
    #: Archived, never deleted — an exercise dropped from the rotation still has
    #: to explain the sets recorded against it.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class StrengthWorkoutTemplate(Base):
    """A reusable workout template with ordered exercise targets.

    Templates are mutable, and that is safe: a session copies its prescription
    into ``StrengthWorkoutExercise.prescription`` when it starts, so editing a
    template changes only what happens *next*. History-safety comes from the
    snapshot, not from freezing the template — which is why ``name`` can stay
    unique and human-readable instead of accumulating "(v3)" suffixes.

    ``version`` is bumped on edit purely so a session can record which revision
    it was started from.
    """

    __tablename__ = "strength_workout_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    #: Null for the seeded templates, which belong to no one in particular.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    estimated_duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class StrengthTemplateExercise(Base):
    """One prescribed exercise in a template.

    Note the unique constraint on (template, exercise): an exercise appears at
    most once per template. That rules out legitimate patterns like squatting
    at the start and again as a back-off — recorded as a known limitation
    rather than worked around, since the constraint predates this work and
    programme days (which have no such limit) are the richer planning surface.
    """

    __tablename__ = "strength_template_exercises"

    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("strength_workout_templates.id"), index=True
    )
    exercise_id: Mapped[int] = mapped_column(ForeignKey("strength_exercises.id"), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    section: Mapped[str] = mapped_column(String(20), default="main")
    superset_group: Mapped[str | None] = mapped_column(String(8), nullable=True)
    target_sets: Mapped[int] = mapped_column(Integer, default=3)
    target_reps: Mapped[int] = mapped_column(Integer, default=8)
    rep_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rep_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_rpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_rir: Mapped[float | None] = mapped_column(Float, nullable=True)
    rest_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tempo: Mapped[str] = mapped_column(String(16), default="")
    progression_rule: Mapped[str] = mapped_column(String(24), default="manual")
    progression_config: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")

    __table_args__ = (
        UniqueConstraint("template_id", "exercise_id", name="uq_strength_template_exercise"),
    )


class StrengthWorkout(Base):
    """A strength session that was actually started.

    ``readiness_snapshot`` is copied in at start time rather than joined at
    read time. Apple Health revises sleep and HRV for a day after the fact, so
    a live join would quietly rewrite the readiness a session was performed
    under — and any correlation drawn from it. The snapshot is what was true
    when the operator walked into the gym.
    """

    __tablename__ = "strength_workouts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("strength_workout_templates.id"), nullable=True
    )
    planned_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("strength_planned_sessions.id"), nullable=True, index=True
    )
    programme_id: Mapped[int | None] = mapped_column(
        ForeignKey("strength_programmes.id"), nullable=True, index=True
    )
    programme_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name: Mapped[str] = mapped_column(String(160), default="Strength Workout")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    default_rest_seconds: Mapped[int] = mapped_column(Integer, default=120)
    location: Mapped[str] = mapped_column(String(120), default="")

    # --- state at the time of training ------------------------------------ #
    bodyweight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    readiness_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    energy_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mood_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    session_rpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    pain_notes: Mapped[str] = mapped_column(Text, default="")
    abandoned_reason: Mapped[str] = mapped_column(String(200), default="")

    notes: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(24), default="manual")
    #: Set when this session came from an import, so foreign records stay
    #: identifiable and a re-import cannot duplicate them.
    import_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    #: Links to the Apple Health activity covering the same period, when one
    #: exists — giving the session real HR and calorie data it cannot self-report.
    workout_id: Mapped[int | None] = mapped_column(
        ForeignKey("workouts.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("ix_strength_workout_user_started", "user_id", "started_at"),
    )


class StrengthWorkoutExercise(Base):
    """An exercise inside one workout, with ordered set entries.

    ``classification_snapshot`` freezes the exercise's muscle and movement
    tagging as it stood that day. Reclassifying an exercise later (deciding
    Romanian deadlifts are hinge-primary rather than hamstring-primary) would
    otherwise silently restate years of muscle-group volume. Both readings stay
    available: the snapshot for "what I believed then", the live join for
    "under today's classification".
    """

    __tablename__ = "strength_workout_exercises"

    id: Mapped[int] = mapped_column(primary_key=True)
    workout_id: Mapped[int] = mapped_column(ForeignKey("strength_workouts.id"), index=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("strength_exercises.id"), index=True)
    programme_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("strength_programme_items.id"), nullable=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    section: Mapped[str] = mapped_column(String(20), default="main")
    superset_group: Mapped[str | None] = mapped_column(String(8), nullable=True)
    target_sets: Mapped[int] = mapped_column(Integer, default=3)
    target_reps: Mapped[int] = mapped_column(Integer, default=8)
    #: The prescription this exercise was performed against, copied at start.
    prescription: Mapped[dict] = mapped_column(JSON, default=dict)
    classification_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)

    #: The operator swapped the prescribed movement. Kept with its reason —
    #: "leg press machine taken" and "knee hurt" imply different follow-ups.
    substituted_from_id: Mapped[int | None] = mapped_column(
        ForeignKey("strength_exercises.id"), nullable=True
    )
    substitution_reason: Mapped[str] = mapped_column(String(200), default="")
    technique_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pain_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    equipment_variation: Mapped[str] = mapped_column(String(120), default="")
    #: Seat height, pin position, handle — the settings that make a machine
    #: load reproducible. Without them, machine numbers are not comparable.
    machine_settings: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class StrengthSetEntry(Base):
    """One logged set — the atomic record the whole dataset is built from.

    Everything here is a separate column rather than a JSON blob because these
    are exactly the fields longitudinal queries filter and group on. "Show my
    working sets between 3 and 6 reps at RPE 8+ over two years" has to be an
    index scan, not a full-table JSON parse.

    Corrections do not delete. ``voided_at`` retires a row from statistics
    while keeping it readable, and ``edit_history`` keeps prior values. A
    mistyped 200 kg bench would otherwise stand as a permanent PR, or vanish
    without trace — both worse than an auditable correction.
    """

    __tablename__ = "strength_set_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    workout_exercise_id: Mapped[int] = mapped_column(
        ForeignKey("strength_workout_exercises.id"), index=True
    )
    set_number: Mapped[int] = mapped_column(Integer, default=1)
    set_type: Mapped[str] = mapped_column(String(16), default="working", index=True)

    # --- load and work ---------------------------------------------------- #
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    reps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Share of bodyweight the movement actually loads (~0.65 for a push-up).
    #: Configurable and transparent — it is an estimate, not a measurement.
    bodyweight_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Band or machine assistance. Subtracts from effective load, so an
    #: assisted pull-up getting *easier* shows as progress, not regression.
    assistance_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Bodyweight at the time, copied from health data. Re-reading it later
    #: would silently restate every historical bodyweight-exercise volume.
    bodyweight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Unilateral work done separately per side. Null for bilateral sets.
    left_reps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    right_reps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    left_weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    right_weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- effort and execution --------------------------------------------- #
    rpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    rir: Mapped[float | None] = mapped_column(Float, nullable=True)
    tempo: Mapped[str] = mapped_column(String(16), default="")
    rest_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    to_failure: Mapped[bool] = mapped_column(default=False)
    has_partials: Mapped[bool] = mapped_column(default=False)
    rom_quality: Mapped[str] = mapped_column(String(16), default="")  # full|partial|assisted
    #: For drop sets and rest-pause: the set this one hangs off. Keeps a drop
    #: from being counted as an independent working set.
    parent_set_id: Mapped[int | None] = mapped_column(
        ForeignKey("strength_set_entries.id"), nullable=True
    )
    superset_group: Mapped[str | None] = mapped_column(String(8), nullable=True)

    completed: Mapped[bool] = mapped_column(default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")

    # --- provenance and correction ---------------------------------------- #
    source: Mapped[str] = mapped_column(String(24), default="manual")
    #: Client-supplied key making set creation idempotent, so a retry over a
    #: flaky gym connection cannot silently duplicate a set.
    client_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    void_reason: Mapped[str] = mapped_column(String(200), default="")
    #: Append-only list of prior values, newest last.
    edit_history: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "workout_exercise_id", "set_number", name="uq_strength_set_exercise_number"
        ),
        UniqueConstraint("client_key", name="uq_strength_set_client_key"),
        Index("ix_strength_set_type_completed", "set_type", "completed"),
    )


class StrengthPersonalRecord(Base):
    """A personal record, traceable to the exact set that set it.

    ``previous_value`` is stored alongside rather than looked up, so a record
    can always state what it beat even after the record it beat is superseded
    or its set is voided.

    ``is_active`` is false once beaten — records are kept, not overwritten, so
    the progression of a lift is itself a readable series. ``invalidated_at``
    is different and deliberate: it marks a record disowned because the set
    behind it was a typo, and those must never reappear as "beaten".
    """

    __tablename__ = "strength_personal_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("strength_exercises.id"), index=True)
    workout_id: Mapped[int] = mapped_column(ForeignKey("strength_workouts.id"), index=True)
    set_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("strength_set_entries.id"), nullable=True
    )
    programme_id: Mapped[int | None] = mapped_column(
        ForeignKey("strength_programmes.id"), nullable=True
    )
    record_type: Mapped[str] = mapped_column(String(24), default="heaviest_weight", index=True)
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(8), default="kg")
    #: For ``most_reps_at_weight`` / ``best_at_rep_target``: the weight or rep
    #: count the record is *at*. A 5-rep best is meaningless without the 5.
    qualifier: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: e.g. "epley" — a 1RM record has to say which formula produced it, or it
    #: cannot be compared with one computed under a different default.
    calculation_method: Mapped[str] = mapped_column(String(24), default="measured")
    previous_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    previous_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("strength_personal_records.id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(default=True, index=True)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    achieved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    __table_args__ = (
        Index("ix_strength_pr_lookup", "user_id", "exercise_id", "record_type", "is_active"),
    )


class FitnessRoute(Base):
    """A recognisable route that can have many workout attempts."""

    __tablename__ = "fitness_routes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    sport_type: Mapped[str] = mapped_column(String(24), default="run")
    description: Mapped[str] = mapped_column(Text, default="")
    distance_meters: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    start_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    route_geometry: Mapped[list] = mapped_column(JSON, default=list)
    encoded_polyline: Mapped[str] = mapped_column(Text, default="")
    elevation_gain_meters: Mapped[float | None] = mapped_column(Float, nullable=True)
    difficulty_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RouteAttempt(Base):
    """A completed workout assigned to a route."""

    __tablename__ = "route_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("fitness_routes.id"), index=True)
    workout_id: Mapped[int] = mapped_column(ForeignKey("workouts.id"), index=True)
    attempt_date: Mapped[date] = mapped_column(Date, index=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    moving_time_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    distance_meters: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_pace_seconds_per_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_heart_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_heart_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    elevation_gain_meters: Mapped[float | None] = mapped_column(Float, nullable=True)
    route_match_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    manually_tagged: Mapped[bool] = mapped_column(default=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("route_id", "workout_id", name="uq_route_workout_attempt"),
    )


class RouteSegment(Base):
    """A named slice of a route, e.g. first climb or final kilometre."""

    __tablename__ = "route_segments"

    id: Mapped[int] = mapped_column(primary_key=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("fitness_routes.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    start_distance_meters: Mapped[float] = mapped_column(Float)
    end_distance_meters: Mapped[float] = mapped_column(Float)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RouteSegmentAttempt(Base):
    """Per-attempt performance for a RouteSegment, when samples allow it."""

    __tablename__ = "route_segment_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    segment_id: Mapped[int] = mapped_column(ForeignKey("route_segments.id"), index=True)
    route_attempt_id: Mapped[int] = mapped_column(ForeignKey("route_attempts.id"), index=True)
    workout_id: Mapped[int] = mapped_column(ForeignKey("workouts.id"), index=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    average_pace_seconds_per_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_heart_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_heart_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        UniqueConstraint("segment_id", "route_attempt_id", name="uq_segment_route_attempt"),
    )


class FitnessCardTemplate(Base):
    """A user-created palette card: a custom training stimulus, droppable.

    Built-in cards live in ``fitness_service.SESSION_LIBRARY``; these are the
    extra ones the user defines. ``key`` is the stable identifier stored on each
    placed ``FitnessSession.session_type`` (so custom cards survive renames of
    their display title).
    """

    __tablename__ = "fitness_card_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    key: Mapped[str] = mapped_column(String(40), index=True)  # e.g. "CUSTOM-7F3A"
    title: Mapped[str] = mapped_column(String(60), default="Custom Session")
    color: Mapped[str] = mapped_column(String(9), default="#2ee6ff")
    category: Mapped[str] = mapped_column(String(16), default="cardio")  # strength|cardio|mobility|recovery
    intensity: Mapped[str] = mapped_column(String(8), default="MOD")
    duration_min: Mapped[int] = mapped_column(Integer, default=45)
    recovery_cost: Mapped[int] = mapped_column(Integer, default=3)  # 0..5
    goal: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# --------------------------------------------------------------------------- #
# Career — a local, hand-editable career observatory (no external integration)
# --------------------------------------------------------------------------- #
class CareerProfile(Base):
    """The current role + how it feels: one editable profile per user.

    ``satisfaction`` is a 0–100 self-rating. The jeopardy / resilience matrices
    are stored as JSON factor-weight maps so the deterministic scorer can read
    them without schema churn.
    """

    __tablename__ = "career_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, unique=True)
    role_title: Mapped[str] = mapped_column(String(120), default="")
    employer: Mapped[str] = mapped_column(String(120), default="")
    started_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    satisfaction: Mapped[int] = mapped_column(Integer, default=50)  # 0..100
    notes: Mapped[str] = mapped_column(Text, default="")
    # Editable factor scores (0..100) for the two matrices.
    jeopardy: Mapped[dict] = mapped_column(JSON, default=dict)
    resilience: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class CareerGoal(Base):
    """A career goal / milestone with a target date and 0–100 progress."""

    __tablename__ = "career_goals"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0..100
    status: Mapped[str] = mapped_column(String(24), default="active")  # active|done|paused
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CareerSkill(Base):
    """A skill / competency with self-rated proficiency and momentum."""

    __tablename__ = "career_skills"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    proficiency: Mapped[int] = mapped_column(Integer, default=50)  # 0..100
    momentum: Mapped[str] = mapped_column(String(12), default="flat")  # up|flat|down
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CareerOpportunity(Base):
    """A role / opportunity in the pipeline with its current stage."""

    __tablename__ = "career_opportunities"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(120))
    company: Mapped[str] = mapped_column(String(120), default="")
    stage: Mapped[str] = mapped_column(String(24), default="lead")  # see PIPELINE_STAGES
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CareerNote(Base):
    """A career journal note: reflection, decision log, or planning scratchpad."""

    __tablename__ = "career_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(160), default="Career note")
    body: Mapped[str] = mapped_column(Text, default="")
    tag: Mapped[str] = mapped_column(String(40), default="reflection")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class CareerPlanStep(Base):
    """A deliberate career move with horizon, status and progress."""

    __tablename__ = "career_plan_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    horizon: Mapped[str] = mapped_column(String(24), default="next")  # now|next|later
    status: Mapped[str] = mapped_column(String(24), default="planned")  # planned|active|blocked|done
    progress: Mapped[int] = mapped_column(Integer, default=0)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class TraineeshipApplication(Base):
    """A traineeship/apprenticeship/graduate-programme application tracker."""

    __tablename__ = "traineeship_applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    programme: Mapped[str] = mapped_column(String(160))
    provider: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(28), default="researching")
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    contact: Mapped[str] = mapped_column(String(120), default="")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


# --------------------------------------------------------------------------- #
# Stoic — local reflective practice/check-ins
# --------------------------------------------------------------------------- #
class StoicEntry(Base):
    """A local Stoic check-in for days where external sources are sparse."""

    __tablename__ = "stoic_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    virtue_focus: Mapped[str] = mapped_column(String(24), default="wisdom")
    control_pct: Mapped[int] = mapped_column(Integer, default=50)
    reflected: Mapped[bool] = mapped_column(default=False)
    served_others: Mapped[bool] = mapped_column(default=False)
    faced_hard_thing: Mapped[bool] = mapped_column(default=False)
    restrained_impulse: Mapped[bool] = mapped_column(default=False)
    study_minutes: Mapped[int] = mapped_column(Integer, default=0)
    reflection: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_stoic_user_day"),)


# --------------------------------------------------------------------------- #
# Mind — local mental health and mindfulness planning
# --------------------------------------------------------------------------- #
class MentalCheckIn(Base):
    """Daily subjective state check-in, bookending the day.

    Non-clinical: mood, anxiety, stress and energy are planning signals only.
    Severe distress enables concise signposting in the UI without turning the
    whole feature into a medical tool.

    One row per day carries both bookends: the morning fields (mood, energy,
    anxiety, sleep_quality, intention, mood factors) and the evening fields
    (stress, day_rating, evening_note, thought record). ``extra`` holds the
    structured extras — ``factors`` (list of mood-influence tags),
    ``intention_done`` (bool), ``thought_record`` (CBT situation/thought/
    balanced-thought dict) — so the schema stays additive.
    """

    __tablename__ = "mental_checkins"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    mood: Mapped[int] = mapped_column(Integer, default=5)  # 1..10
    anxiety: Mapped[int] = mapped_column(Integer, default=3)  # 1..10
    stress: Mapped[int] = mapped_column(Integer, default=3)  # 1..10
    energy: Mapped[int] = mapped_column(Integer, default=5)  # 1..10
    sleep_quality: Mapped[int] = mapped_column(Integer, default=5)  # 1..10
    intention: Mapped[str] = mapped_column(String(300), default="")  # morning
    day_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)  # evening 1..10
    evening_note: Mapped[str] = mapped_column(Text, default="")  # evening reflection
    triggers: Mapped[str] = mapped_column(Text, default="")
    protective_actions: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    extra: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_mental_user_day"),)


class MindfulnessSession(Base):
    """A locally logged mindfulness practice session."""

    __tablename__ = "mindfulness_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=3)
    kind: Mapped[str] = mapped_column(String(24), default="meditation")
    source: Mapped[str] = mapped_column(String(24), default="manual")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# --------------------------------------------------------------------------- #
# Diploma — a local, hand-editable study tracker (no external integration)
# --------------------------------------------------------------------------- #
class DiplomaProgram(Base):
    """The qualification being studied: name, awarding body, credits required."""

    __tablename__ = "diploma_programs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, unique=True)
    name: Mapped[str] = mapped_column(String(160), default="Diploma")
    awarding_body: Mapped[str] = mapped_column(String(120), default="")
    credits_required: Mapped[int] = mapped_column(Integer, default=120)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class DiplomaModule(Base):
    """A course module/unit: credits, weighting, and grade (when complete)."""

    __tablename__ = "diploma_modules"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    credits: Mapped[int] = mapped_column(Integer, default=15)
    weight: Mapped[float] = mapped_column(Float, default=1.0)  # toward final average
    grade: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0..100, None=ongoing
    status: Mapped[str] = mapped_column(String(16), default="ongoing")  # ongoing|done
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DiplomaAssessment(Base):
    """An assignment or exam tracked by STATUS / preparedness — not by hours.

    ``kind`` distinguishes coursework (submission status) from exams
    (preparedness). ``readiness`` is a 0–100 self-rating used for exams.
    """

    __tablename__ = "diploma_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    module_id: Mapped[int | None] = mapped_column(
        ForeignKey("diploma_modules.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(16), default="assignment")  # assignment|exam
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Coursework status: not_started|in_progress|submitted|graded
    # Exam status: revising|ready  (readiness carries the 0..100 detail)
    status: Mapped[str] = mapped_column(String(16), default="not_started")
    readiness: Mapped[int] = mapped_column(Integer, default=0)  # 0..100 (exams)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# --------------------------------------------------------------------------- #
# Calendar (iOS / iCloud via macOS EventKit)
# --------------------------------------------------------------------------- #
class CalendarEvent(Base):
    """A calendar event mirrored from the OS calendar (iCloud via EventKit).

    Read-only mirror: ORION never writes back to the system calendar. Events are
    upserted by their stable ``ext_id`` (EventKit eventIdentifier) so re-syncs
    update in place rather than duplicating.
    """

    __tablename__ = "calendar_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    ext_id: Mapped[str] = mapped_column(String(255), index=True)  # EventKit identifier
    title: Mapped[str] = mapped_column(String(400), default="")
    location: Mapped[str | None] = mapped_column(String(400), nullable=True)
    calendar_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    all_day: Mapped[bool] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)

    __table_args__ = (
        UniqueConstraint("user_id", "ext_id", name="uq_calendar_user_ext"),
    )


# --------------------------------------------------------------------------- #
# Tasks (two-way sync with the companion "tasks" Supabase app)
# --------------------------------------------------------------------------- #
class Task(Base):
    """A task mirrored from / pushed to the companion tasks app (Supabase).

    Columns mirror the Supabase ``tasks`` table so sync is a near-1:1 mapping.
    ``ext_id`` holds the Supabase row UUID. ``dirty`` marks a row edited locally
    and not yet pushed back; ``pending_delete`` queues a remote delete. New rows
    created locally have a null ``ext_id`` until their first push assigns one.
    """

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    ext_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(400), default="")
    area: Mapped[str | None] = mapped_column(String(160), nullable=True)
    category: Mapped[str | None] = mapped_column(String(160), nullable=True)
    priority: Mapped[str] = mapped_column(String(16), default="medium")  # low|medium|high
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|done
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    recurrence: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sort_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remote_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Local two-way-sync bookkeeping.
    dirty: Mapped[bool] = mapped_column(Integer, default=0)
    pending_delete: Mapped[bool] = mapped_column(Integer, default=0)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CaptureInboxItem(Base):
    """A mobile/desktop quick-capture item waiting to be triaged."""

    __tablename__ = "capture_inbox_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    text: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(40), default="desktop")
    status: Mapped[str] = mapped_column(String(24), default="new")  # new|triaged|archived
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)
    dirty: Mapped[bool] = mapped_column(Integer, default=1)
    pending_delete: Mapped[bool] = mapped_column(Integer, default=0)


# --------------------------------------------------------------------------- #
# Operator settings (targets, location, units, theme)
# --------------------------------------------------------------------------- #
class UserSetting(Base):
    """One typed setting per row; values are JSON so callers keep native types.

    Read/write through ``app.domains.settings_service`` which owns the defaults
    and validation — nothing else should touch this table directly.
    """

    __tablename__ = "user_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    key: Mapped[str] = mapped_column(String(80), index=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)  # {"v": <payload>}
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_setting_user_key"),)


# --------------------------------------------------------------------------- #
# Nutrition (zero-subscription: local foods + Open Food Facts + generics)
# --------------------------------------------------------------------------- #
class NutritionFood(Base):
    """A food the operator has used: scanned, searched, corrected or created.

    Macros are stored per 100 g; ``FoodLog`` snapshots the portion maths so a
    later correction never rewrites history. ``source_provider`` is one of
    user | off | generic | manual, and user-corrected rows always win lookups.
    """

    __tablename__ = "nutrition_foods"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    brand: Mapped[str] = mapped_column(String(200), default="")
    barcode: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    source_provider: Mapped[str] = mapped_column(String(24), default="manual")
    source_confidence: Mapped[str] = mapped_column(String(16), default="medium")  # high|medium|low
    serving_size: Mapped[float | None] = mapped_column(Float, nullable=True)  # grams per serving
    serving_unit: Mapped[str] = mapped_column(String(60), default="serving")
    calories_100g: Mapped[float | None] = mapped_column(Float, nullable=True)
    protein_100g: Mapped[float | None] = mapped_column(Float, nullable=True)
    carbs_100g: Mapped[float | None] = mapped_column(Float, nullable=True)
    fat_100g: Mapped[float | None] = mapped_column(Float, nullable=True)
    fibre_100g: Mapped[float | None] = mapped_column(Float, nullable=True)
    sugar_100g: Mapped[float | None] = mapped_column(Float, nullable=True)
    saturated_fat_100g: Mapped[float | None] = mapped_column(Float, nullable=True)
    sodium_mg_100g: Mapped[float | None] = mapped_column(Float, nullable=True)
    micronutrients: Mapped[dict] = mapped_column(JSON, default=dict)
    user_corrected: Mapped[bool] = mapped_column(Integer, default=0)
    saved: Mapped[bool] = mapped_column(Integer, default=0)  # pinned to "saved foods"
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class FoodLog(Base):
    """One logged intake: a food at a time in a portion, macros snapshotted."""

    __tablename__ = "food_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    food_id: Mapped[int | None] = mapped_column(
        ForeignKey("nutrition_foods.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(300))  # snapshot; survives food edits
    meal_type: Mapped[str] = mapped_column(String(24), default="snack")  # breakfast|lunch|dinner|snack
    day: Mapped[date] = mapped_column(Date, index=True)
    logged_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    grams: Mapped[float | None] = mapped_column(Float, nullable=True)
    servings: Mapped[float | None] = mapped_column(Float, nullable=True)
    calories: Mapped[float | None] = mapped_column(Float, nullable=True)
    protein: Mapped[float | None] = mapped_column(Float, nullable=True)
    carbs: Mapped[float | None] = mapped_column(Float, nullable=True)
    fat: Mapped[float | None] = mapped_column(Float, nullable=True)
    fibre: Mapped[float | None] = mapped_column(Float, nullable=True)
    sugar: Mapped[float | None] = mapped_column(Float, nullable=True)
    saturated_fat: Mapped[float | None] = mapped_column(Float, nullable=True)
    sodium_mg: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(24), default="manual")  # scan|search|quick|repeat|manual
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MealTemplate(Base):
    """A reusable meal: items are [{food_id, name, grams, servings}, ...]."""

    __tablename__ = "meal_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    items: Mapped[list] = mapped_column(JSON, default=list)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# --------------------------------------------------------------------------- #
# External signals (weather, air, holidays, FX) — server-side TTL cache
# --------------------------------------------------------------------------- #
class ExternalSignalCache(Base):
    """Cached response from a free, keyless public API.

    A stale row is still served (marked stale) when the upstream is down, so
    signals degrade gracefully instead of blanking the UI.
    """

    __tablename__ = "external_signal_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)  # weather|air|holidays|fx
    key: Mapped[str] = mapped_column(String(160), default="")  # e.g. rounded lat,lon
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    ok: Mapped[bool] = mapped_column(Integer, default=1)
    error: Mapped[str] = mapped_column(String(300), default="")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (UniqueConstraint("kind", "key", name="uq_signal_kind_key"),)


# --------------------------------------------------------------------------- #
# Plan: habits and goals
# --------------------------------------------------------------------------- #
# These are the operator's own intentions, so they are the one part of the
# schema with no upstream connector — every row is entered by hand. Read/write
# through ``app.domains.plan_service``; streaks and goal progress are computed
# there, never stored, so they cannot drift from the entries that justify them.
class Habit(Base):
    """A recurring behaviour the operator intends to keep up.

    ``cadence`` + ``target_per_period`` express the commitment ("3 times per
    week"), which is what a streak is judged against. ``domain`` matches the
    UI's semantic domain keys (see ``frontend/lib/domains.ts``) so the habit
    inherits the same colour as everything else in its domain.
    """

    __tablename__ = "habits"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(160), default="")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    domain: Mapped[str] = mapped_column(String(24), default="neutral")
    cadence: Mapped[str] = mapped_column(String(16), default="daily")  # daily|weekly
    target_per_period: Mapped[int] = mapped_column(Integer, default=1)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # Archived rather than deleted: a habit you gave up on is still the
    # explanation for a broken streak, so its entries must survive.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)

    entries: Mapped[list["HabitEntry"]] = relationship(
        back_populates="habit", cascade="all, delete-orphan"
    )


class HabitEntry(Base):
    """One day's record for a habit.

    A row exists only for days the habit was actually done — absence means not
    done, so there is no "false" state to keep in sync. ``count`` covers habits
    done more than once in a day; the unique constraint keeps one row per day.
    """

    __tablename__ = "habit_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    habit_id: Mapped[int] = mapped_column(ForeignKey("habits.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    count: Mapped[int] = mapped_column(Integer, default=1)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    habit: Mapped[Habit] = relationship(back_populates="entries")

    __table_args__ = (UniqueConstraint("habit_id", "day", name="uq_habit_entry_day"),)


class Goal(Base):
    """A target the operator is working toward.

    Progress comes from one of two places, and the distinction is surfaced in
    the UI rather than blurred: if ``metric_kind`` is set, current value is
    computed from real measured data and ``manual_value`` is ignored; otherwise
    the operator maintains ``manual_value`` by hand. ``direction`` says which
    way is progress, so a falling weight goal is not read as a regression.
    """

    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    domain: Mapped[str] = mapped_column(String(24), default="neutral")
    # When set, names a metric ORION already measures (e.g. "run_distance"),
    # and progress is derived from it instead of typed in.
    metric_kind: Mapped[str | None] = mapped_column(String(60), nullable=True)
    metric_window_days: Mapped[int] = mapped_column(Integer, default=7)
    baseline_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    manual_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(24), default="")
    direction: Mapped[str] = mapped_column(String(12), default="increase")  # increase|decrease
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|achieved|abandoned
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)


# --------------------------------------------------------------------------- #
# Strength training — programmes, planning and progression
# --------------------------------------------------------------------------- #
# The tables above (``strength_exercises`` … ``strength_personal_records``) were
# built for one job: log a session quickly on a phone. What follows adds the
# layer that turns those logs into a *dataset* — what was prescribed, what was
# actually done, and why the prescription changed.
#
# Three rules run through all of it, because each one is a mistake that is
# cheap to avoid now and impossible to repair later:
#
# 1. **Plans are copied into sessions, not referenced by them.** A completed
#    session stores the prescription it was performed against. Editing a
#    template next month must not rewrite what last month's session was asked
#    to do — otherwise adherence becomes unanswerable.
# 2. **Nothing performed is ever deleted.** Corrections set ``voided_at`` and
#    keep the original value. A set that never existed and a set that was
#    entered wrong are different facts, and only one of them should vanish
#    from a chart.
# 3. **Everything is stored in kilograms.** Display units are a preference.
#    Storing whatever the user was typing that month makes every longitudinal
#    query a unit-archaeology exercise.

# Vocabularies. Kept as strings rather than SQL enums: SQLite cannot alter an
# enum in place, and these lists grow (the brief already anticipates new set
# types and measurement kinds).
MOVEMENT_PATTERNS = (
    "horizontal_push", "vertical_push", "horizontal_pull", "vertical_pull",
    "squat", "hinge", "lunge", "carry", "elbow_flexion", "elbow_extension",
    "knee_flexion", "knee_extension", "calf", "core_flexion", "core_extension",
    "anti_extension", "anti_rotation", "rotation", "other",
)
#: How load is applied. Drives volume maths — an assisted pull-up and a
#: weighted pull-up move the load in opposite directions.
LOAD_TYPES = ("external", "bodyweight", "weighted_bodyweight", "assisted")
#: What a set actually measures. A plank is not badly-recorded reps.
MEASUREMENT_KINDS = ("reps", "duration", "distance")
LATERALITIES = ("bilateral", "unilateral_alternating", "unilateral_separate")
SET_TYPES = (
    "warmup", "working", "top_set", "backoff", "amrap", "drop",
    "rest_pause", "myo_rep", "technique", "test", "failure",
)
#: Only these count toward working-set and hard-set statistics. Warm-ups and
#: technique work are real training but must not inflate volume.
WORKING_SET_TYPES = (
    "working", "top_set", "backoff", "amrap", "drop",
    "rest_pause", "myo_rep", "failure", "test",
)
SESSION_STATUSES = (
    "planned", "active", "completed", "partial", "abandoned", "skipped", "rescheduled",
)
PROGRESSION_RULES = (
    "fixed_load", "double_progression", "rep_range", "percentage",
    "rpe_target", "rir_target", "top_set_backoff", "amrap_triggered",
    "manual", "deload",
)
PR_TYPES = (
    "heaviest_weight", "most_reps_at_weight", "best_e1rm", "best_set_volume",
    "best_session_volume", "best_at_rep_target", "longest_duration", "fastest_time",
)


class StrengthProgramme(Base):
    """A multi-week training plan.

    Versioned rather than mutated: ``version`` increments and ``supersedes_id``
    points back, so a session completed under v1 keeps pointing at v1's
    prescriptions even after v2 exists. Without this, "did I follow the
    programme?" silently becomes "does today's programme resemble what I did?".
    """

    __tablename__ = "strength_programmes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(160), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    goal: Mapped[str] = mapped_column(String(60), default="")  # strength|hypertrophy|…
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    weeks: Mapped[int] = mapped_column(Integer, default=4)
    days_per_week: Mapped[int] = mapped_column(Integer, default=3)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    supersedes_id: Mapped[int | None] = mapped_column(
        ForeignKey("strength_programmes.id"), nullable=True
    )
    notes: Mapped[str] = mapped_column(Text, default="")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)

    blocks: Mapped[list[StrengthProgrammeBlock]] = relationship(
        back_populates="programme", cascade="all, delete-orphan"
    )
    days: Mapped[list[StrengthProgrammeDay]] = relationship(
        back_populates="programme", cascade="all, delete-orphan"
    )


class StrengthProgrammeBlock(Base):
    """A phase within a programme (accumulation, intensification, deload)."""

    __tablename__ = "strength_programme_blocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    programme_id: Mapped[int] = mapped_column(
        ForeignKey("strength_programmes.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), default="")
    focus: Mapped[str] = mapped_column(String(60), default="")
    start_week: Mapped[int] = mapped_column(Integer, default=1)
    end_week: Mapped[int] = mapped_column(Integer, default=1)
    is_deload: Mapped[bool] = mapped_column(default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    programme: Mapped[StrengthProgramme] = relationship(back_populates="blocks")


class StrengthProgrammeDay(Base):
    """One training day in the programme grid (week N, day M)."""

    __tablename__ = "strength_programme_days"

    id: Mapped[int] = mapped_column(primary_key=True)
    programme_id: Mapped[int] = mapped_column(
        ForeignKey("strength_programmes.id"), index=True
    )
    week_number: Mapped[int] = mapped_column(Integer, default=1, index=True)
    day_number: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(120), default="")
    focus: Mapped[str] = mapped_column(String(60), default="")
    # 0=Mon … 6=Sun. Null means "any day this week" — flexible scheduling is a
    # real choice, not missing data, so it is not defaulted to Monday.
    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")

    programme: Mapped[StrengthProgramme] = relationship(back_populates="days")
    items: Mapped[list[StrengthProgrammeItem]] = relationship(
        back_populates="day", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "programme_id", "week_number", "day_number", name="uq_programme_day"
        ),
    )


class StrengthProgrammeItem(Base):
    """One prescribed exercise on a programme day.

    The prescription is deliberately expressive — a rep *range* with an RPE cap
    is a different instruction from a fixed rep count, and flattening the two
    would make progression rules unable to tell whether a target was met.
    """

    __tablename__ = "strength_programme_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    day_id: Mapped[int] = mapped_column(ForeignKey("strength_programme_days.id"), index=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("strength_exercises.id"), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    section: Mapped[str] = mapped_column(String(20), default="main")  # warmup|main|accessory
    # Exercises sharing a superset group are alternated. Null = performed straight.
    superset_group: Mapped[str | None] = mapped_column(String(8), nullable=True)
    target_sets: Mapped[int] = mapped_column(Integer, default=3)
    rep_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rep_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    percent_1rm: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_rpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_rir: Mapped[float | None] = mapped_column(Float, nullable=True)
    tempo: Mapped[str] = mapped_column(String(16), default="")
    rest_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warmup_note: Mapped[str] = mapped_column(Text, default="")
    progression_rule: Mapped[str] = mapped_column(String(24), default="manual")
    progression_config: Mapped[dict] = mapped_column(JSON, default=dict)
    #: Exercise IDs acceptable when equipment is busy or unavailable.
    substitution_ids: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")

    day: Mapped[StrengthProgrammeDay] = relationship(back_populates="items")


class StrengthPlannedSession(Base):
    """A scheduled workout — the intention, distinct from what happened.

    Kept separate from ``StrengthWorkout`` rather than folded into it with a
    status flag. A plan that was never started and a session that was started
    and abandoned are different events, and collapsing them would quietly
    inflate adherence.
    """

    __tablename__ = "strength_planned_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    planned_date: Mapped[date] = mapped_column(Date, index=True)
    programme_id: Mapped[int | None] = mapped_column(
        ForeignKey("strength_programmes.id"), nullable=True, index=True
    )
    programme_day_id: Mapped[int | None] = mapped_column(
        ForeignKey("strength_programme_days.id"), nullable=True
    )
    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("strength_workout_templates.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(160), default="")
    status: Mapped[str] = mapped_column(String(16), default="planned", index=True)
    #: Frozen copy of the prescription, so template edits cannot rewrite history.
    prescription: Mapped[list] = mapped_column(JSON, default=list)
    target_duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rescheduled_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    reschedule_reason: Mapped[str] = mapped_column(Text, default="")
    #: Set only when the operator accepted a readiness-based suggestion. An
    #: adjustment ORION proposed and the user declined is not recorded here.
    readiness_adjustment: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class StrengthProgressionEvent(Base):
    """A progression proposal and what the operator decided about it.

    Stored whether accepted or rejected. Rejections are the more interesting
    half of the record: a rule the operator overrides every week is a rule that
    does not fit them, and that is only visible if the misses are kept.
    """

    __tablename__ = "strength_progression_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("strength_exercises.id"), index=True)
    workout_id: Mapped[int | None] = mapped_column(
        ForeignKey("strength_workouts.id"), nullable=True, index=True
    )
    programme_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("strength_programme_items.id"), nullable=True
    )
    rule: Mapped[str] = mapped_column(String(24), default="manual")
    #: Everything the rule looked at, so the proposal can be re-derived later.
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    proposal: Mapped[dict] = mapped_column(JSON, default=dict)
    reason: Mapped[str] = mapped_column(Text, default="")
    decision: Mapped[str] = mapped_column(String(12), default="pending", index=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: What was actually prescribed next time — which may match neither the
    #: proposal nor the previous session, if the operator typed their own.
    applied_prescription: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
