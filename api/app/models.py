"""Tables. Must match migrations/sql/*.sql — the SQL file is the source of truth."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _now():
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text, default="")
    role: Mapped[str] = mapped_column(Text, default="pending")
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    home_showroom: Mapped[str | None] = mapped_column(Text)
    default_class: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _now()
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_hash: Mapped[str | None] = mapped_column(Text)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Entity(Base):
    __tablename__ = "entities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, default="person")
    name: Mapped[str] = mapped_column(Text)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("entities.id"))
    phone: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    name_norm: Mapped[str] = mapped_column(Text)
    phone_norm: Mapped[str | None] = mapped_column(Text)
    email_norm: Mapped[str | None] = mapped_column(Text)
    netsuite_customer_id: Mapped[str | None] = mapped_column(Text)
    merged_into_id: Mapped[int | None] = mapped_column(ForeignKey("entities.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _now()
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    class_code: Mapped[str] = mapped_column(Text)
    project_type: Mapped[str | None] = mapped_column(Text)
    lead_source: Mapped[str | None] = mapped_column(Text)
    lead_showroom: Mapped[str | None] = mapped_column(Text)
    rep_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    default_contact_id: Mapped[int | None] = mapped_column(ForeignKey("entities.id"))
    status: Mapped[str] = mapped_column(Text, default="active")
    hold_until: Mapped[date | None] = mapped_column(Date)
    hold_reason: Mapped[str | None] = mapped_column(Text)
    lost_reason: Mapped[str | None] = mapped_column(Text)
    lost_note: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    covering_for_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class JobRole(Base):
    __tablename__ = "job_roles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"))
    role: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    started_at: Mapped[datetime] = _now()
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class Area(Base):
    __tablename__ = "areas"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    name: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="open")
    hold_until: Mapped[date | None] = mapped_column(Date)
    hold_reason: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    footage: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    footage_source: Mapped[str | None] = mapped_column(Text)
    footage_by: Mapped[str | None] = mapped_column(Text)
    footage_confidence: Mapped[str | None] = mapped_column(Text)
    footage_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class Item(Base):
    __tablename__ = "items"
    netsuite_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(Text)
    sku: Mapped[str | None] = mapped_column(Text)
    size: Mapped[str | None] = mapped_column(Text)
    finish: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_lot: Mapped[bool] = mapped_column(Boolean, default=False)
    is_stock: Mapped[bool] = mapped_column(Boolean, default=False)  # NetSuite custitem4
    unit: Mapped[str | None] = mapped_column(Text)
    unit_id: Mapped[int | None] = mapped_column(Integer)
    synced_at: Mapped[datetime] = _now()


class SyncRun(Base):
    """One NetSuite sync attempt. Written with plain SQL, outside the audit log."""

    __tablename__ = "sync_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = _now()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, default="running")
    rows_seen: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    started_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class Candidate(Base):
    __tablename__ = "candidates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    source: Mapped[str] = mapped_column(Text)
    netsuite_item_id: Mapped[int | None] = mapped_column(Integer)
    name: Mapped[str | None] = mapped_column(Text)
    supplier: Mapped[str | None] = mapped_column(Text)
    lead_time_weeks: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class CandidateTag(Base):
    __tablename__ = "candidate_tags"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"))
    area_id: Mapped[int] = mapped_column(ForeignKey("areas.id"))
    status: Mapped[str] = mapped_column(Text, default="considering")
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    unit: Mapped[str] = mapped_column(Text, default="sf")
    reason: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _now()
    avail_status: Mapped[str | None] = mapped_column(Text)
    avail_lot: Mapped[str | None] = mapped_column(Text)
    avail_free: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    avail_need: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    avail_note: Mapped[str | None] = mapped_column(Text)
    avail_summary: Mapped[str | None] = mapped_column(Text)  # the story line, written by the check
    avail_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    avail_checked_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class Sample(Base):
    __tablename__ = "samples"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    area_id: Mapped[int | None] = mapped_column(ForeignKey("areas.id"))
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("candidates.id"))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="requested")
    requested_on: Mapped[date] = mapped_column(Date, server_default=func.current_date())
    sent_on: Mapped[date | None] = mapped_column(Date)
    expect_reply_by: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class ScheduledVisit(Base):
    __tablename__ = "scheduled_visits"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    rep_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    showroom: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    purpose: Mapped[str | None] = mapped_column(Text)
    expected: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="scheduled")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    rescheduled_to_id: Mapped[int | None] = mapped_column(ForeignKey("scheduled_visits.id"))
    created_at: Mapped[datetime] = _now()
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    covering_for_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    kind: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    channel: Mapped[str | None] = mapped_column(Text)
    direction: Mapped[str | None] = mapped_column(Text)
    showroom: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    scheduled_visit_id: Mapped[int | None] = mapped_column(ForeignKey("scheduled_visits.id"))
    logged_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _now()


class EventPerson(Base):
    __tablename__ = "event_people"
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), primary_key=True)


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    area_id: Mapped[int | None] = mapped_column(ForeignKey("areas.id"))
    title: Mapped[str] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    assignee_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, default="open")
    severity: Mapped[str] = mapped_column(Text, default="silent")
    outcome_note: Mapped[str | None] = mapped_column(Text)
    needs_rep_attention: Mapped[bool] = mapped_column(Boolean, default=False)
    parent_task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"))
    source_event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id"))
    created_at: Mapped[datetime] = _now()
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str | None] = mapped_column(Text)  # "takeoff", or None for an ordinary step
    covering_for_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class Absence(Base):
    __tablename__ = "absences"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    cover_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="planned")
    took_takeoff: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _now()
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PushSubscription(Base):
    """Written with plain SQL only, so the keys never reach the audit log."""

    __tablename__ = "push_subscriptions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(Text)
    auth: Mapped[str] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failures: Mapped[int] = mapped_column(Integer, default=0)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = _now()
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class JobFile(Base):
    __tablename__ = "job_files"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    area_id: Mapped[int | None] = mapped_column(ForeignKey("areas.id"))
    kind: Mapped[str] = mapped_column(Text, default="plan")
    name: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(Text)
    link_url: Mapped[str | None] = mapped_column(Text)
    link_id: Mapped[int | None] = mapped_column(ForeignKey("job_files.id"))
    status: Mapped[str] = mapped_column(Text, default="ready")
    problem: Mapped[str | None] = mapped_column(Text)
    removed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _now()
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class FileBlob(Base):
    """File bytes. Written and read with plain SQL only — never through the session,
    so the audit log never sees them."""

    __tablename__ = "file_blobs"
    file_id: Mapped[int] = mapped_column(ForeignKey("job_files.id"), primary_key=True)
    data: Mapped[bytes] = mapped_column(LargeBinary)


class Estimate(Base):
    __tablename__ = "estimates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    status: Mapped[str] = mapped_column(Text, default="draft")
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    netsuite_estimate_id: Mapped[int | None] = mapped_column(Integer)


class EstimateArea(Base):
    __tablename__ = "estimate_areas"
    estimate_id: Mapped[int] = mapped_column(ForeignKey("estimates.id"), primary_key=True)
    area_id: Mapped[int] = mapped_column(ForeignKey("areas.id"), primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))


class EstimateLine(Base):
    __tablename__ = "estimate_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    estimate_id: Mapped[int] = mapped_column(ForeignKey("estimates.id"))
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    tag_id: Mapped[int | None] = mapped_column(ForeignKey("candidate_tags.id"))
    area_id: Mapped[int | None] = mapped_column(ForeignKey("areas.id"))
    netsuite_item_id: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    unit: Mapped[str | None] = mapped_column(Text)
    base_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    price_note: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    at: Mapped[datetime] = _now()
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"))
    table_name: Mapped[str] = mapped_column(Text)
    row_id: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    changes: Mapped[dict] = mapped_column(JSONB, default=dict)
    story: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[str | None] = mapped_column(Text)
