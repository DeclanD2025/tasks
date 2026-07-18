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
    """Seeded or custom strength exercise metadata."""

    __tablename__ = "strength_exercises"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    primary_muscle: Mapped[str] = mapped_column(String(32), index=True)
    secondary_muscles: Mapped[list] = mapped_column(JSON, default=list)
    equipment: Mapped[str] = mapped_column(String(40), index=True)
    movement_pattern: Mapped[str] = mapped_column(String(40), default="")
    category: Mapped[str] = mapped_column(String(32), default="strength")
    unilateral: Mapped[bool] = mapped_column(default=False)
    default_sets: Mapped[int] = mapped_column(Integer, default=3)
    default_reps: Mapped[int] = mapped_column(Integer, default=8)
    notes: Mapped[str] = mapped_column(Text, default="")
    is_custom: Mapped[bool] = mapped_column(default=False)
    favorite: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class StrengthWorkoutTemplate(Base):
    """A reusable workout template with ordered exercise targets."""

    __tablename__ = "strength_workout_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class StrengthTemplateExercise(Base):
    __tablename__ = "strength_template_exercises"

    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("strength_workout_templates.id"), index=True
    )
    exercise_id: Mapped[int] = mapped_column(ForeignKey("strength_exercises.id"), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    target_sets: Mapped[int] = mapped_column(Integer, default=3)
    target_reps: Mapped[int] = mapped_column(Integer, default=8)
    notes: Mapped[str] = mapped_column(Text, default="")

    __table_args__ = (
        UniqueConstraint("template_id", "exercise_id", name="uq_strength_template_exercise"),
    )


class StrengthWorkout(Base):
    """An active/completed strength workout."""

    __tablename__ = "strength_workouts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("strength_workout_templates.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(160), default="Strength Workout")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    default_rest_seconds: Mapped[int] = mapped_column(Integer, default=120)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class StrengthWorkoutExercise(Base):
    """An exercise inside one workout, with ordered set entries."""

    __tablename__ = "strength_workout_exercises"

    id: Mapped[int] = mapped_column(primary_key=True)
    workout_id: Mapped[int] = mapped_column(ForeignKey("strength_workouts.id"), index=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("strength_exercises.id"), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    target_sets: Mapped[int] = mapped_column(Integer, default=3)
    target_reps: Mapped[int] = mapped_column(Integer, default=8)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class StrengthSetEntry(Base):
    """One logged set in an active or completed strength workout."""

    __tablename__ = "strength_set_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    workout_exercise_id: Mapped[int] = mapped_column(
        ForeignKey("strength_workout_exercises.id"), index=True
    )
    set_number: Mapped[int] = mapped_column(Integer, default=1)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    reps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    set_type: Mapped[str] = mapped_column(String(16), default="working")
    completed: Mapped[bool] = mapped_column(default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "workout_exercise_id", "set_number", name="uq_strength_set_exercise_number"
        ),
    )


class StrengthPersonalRecord(Base):
    """Personal record achieved by a completed set."""

    __tablename__ = "strength_personal_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("strength_exercises.id"), index=True)
    workout_id: Mapped[int] = mapped_column(ForeignKey("strength_workouts.id"), index=True)
    set_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("strength_set_entries.id"), nullable=True
    )
    record_type: Mapped[str] = mapped_column(String(24), default="top_set")
    value: Mapped[float] = mapped_column(Float)
    achieved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


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
