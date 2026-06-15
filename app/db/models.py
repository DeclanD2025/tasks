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
# Fitness — a local, hand-editable training planner (no external integration)
# --------------------------------------------------------------------------- #
class FitnessPlan(Base):
    """The current training block: an editable name, start date and length.

    One active plan per user for now; ``is_active`` lets future blocks be kept.
    """

    __tablename__ = "fitness_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    block_name: Mapped[str] = mapped_column(String(120), default="Training Block")
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
    sort_order: Mapped[int] = mapped_column(Integer, default=0)  # multiple per day
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
