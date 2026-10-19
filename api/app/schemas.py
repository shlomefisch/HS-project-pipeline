"""What the API accepts. Validation here is the first line; services enforce the business rules."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator


def _strip(v):
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


class _In(BaseModel):
    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------- auth
class GoogleSignIn(_In):
    credential: str


class DevSignIn(_In):
    email: str
    name: str | None = None


# --------------------------------------------------------------- users
class UserUpdate(_In):
    name: str | None = None
    role: Literal["pending", "rep", "back_office", "management", "viewer"] | None = None
    is_admin: bool | None = None
    home_showroom: str | None = None
    default_class: str | None = None
    active: bool | None = None


# ------------------------------------------------------------ entities
class EntityCheck(_In):
    name: str | None = None
    phone: str | None = None
    email: str | None = None


class EntityCreate(_In):
    kind: Literal["person", "company"] = "person"
    name: str = Field(min_length=1)
    company_id: int | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    notes: str | None = None
    # "Create new" is only allowed after the possible duplicates were shown and declined.
    confirm_new: bool = False

    _s = field_validator("name", "phone", "email", "address", "notes", mode="before")(_strip)


class EntityUpdate(_In):
    kind: Literal["person", "company"] | None = None
    name: str | None = None
    company_id: int | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    notes: str | None = None

    _s = field_validator("name", "phone", "email", "address", "notes", mode="before")(_strip)


# --------------------------------------------------------------- tasks
class NextStep(_In):
    title: str = Field(min_length=1)
    assignee_id: int
    due_date: date
    severity: Literal["silent", "notify", "interrupt"] = "silent"
    notes: str | None = None
    area_id: int | None = None


class TaskCreate(NextStep):
    pass


class TaskUpdate(_In):
    title: str | None = None
    notes: str | None = None
    assignee_id: int | None = None
    due_date: date | None = None
    severity: Literal["silent", "notify", "interrupt"] | None = None


class TaskComplete(_In):
    outcome: Literal["done", "blocked", "bad_answer", "skipped"]
    note: str | None = None
    next_step: NextStep | None = None

    _s = field_validator("note", mode="before")(_strip)


# ---------------------------------------------------------------- jobs
class PersonOnJob(_In):
    entity_id: int
    role: Literal["owner", "designer", "contractor", "installer", "pm", "other"]


class FirstEvent(_In):
    kind: Literal["contact", "showroom_visit", "site_visit"] = "contact"
    channel: Literal["phone", "text", "email", "whatsapp", "in_person"] | None = None
    direction: Literal["in", "out"] | None = None
    summary: str = Field(min_length=1)


class JobCreate(_In):
    name: str = Field(min_length=1)
    rep_id: int | None = None
    class_code: str | None = None
    address: str | None = None
    project_type: str | None = None
    lead_source: str | None = None
    lead_showroom: str | None = None
    people: list[PersonOnJob] = Field(min_length=1)
    first_event: FirstEvent | None = None
    next_step: NextStep

    _s = field_validator("name", "address", mode="before")(_strip)


class JobUpdate(_In):
    name: str | None = None
    address: str | None = None
    class_code: str | None = None
    project_type: str | None = None
    lead_source: str | None = None
    lead_showroom: str | None = None
    default_contact_id: int | None = None

    _s = field_validator("name", "address", mode="before")(_strip)


class RepChange(_In):
    rep_id: int


class JobHold(_In):
    until: date
    reason: str = Field(min_length=1)


class JobLose(_In):
    reason: Literal["price", "timing", "competitor", "cancelled", "bought_direct", "other"]
    note: str | None = None

    _s = field_validator("note", mode="before")(_strip)


class JobRevive(_In):
    mode: Literal["resume", "fresh"]
    next_step: NextStep


# ----------------------------------------------------------- selection
class AreaCreate(_In):
    name: str = Field(min_length=1)

    _s = field_validator("name", mode="before")(_strip)


class AreaUpdate(_In):
    name: str | None = None
    status: Literal["open", "decided", "dropped", "on_hold"] | None = None
    hold_until: date | None = None
    hold_reason: str | None = None
    sort_order: int | None = None


class CandidateCreate(_In):
    source: Literal["stock", "local", "overseas"]
    netsuite_item_id: int | None = None
    name: str | None = None
    supplier: str | None = None
    lead_time_weeks: int | None = Field(default=None, ge=0, le=104)
    notes: str | None = None
    area_ids: list[int] = []

    _s = field_validator("name", "supplier", "notes", mode="before")(_strip)


class CandidateUpdate(_In):
    name: str | None = None
    supplier: str | None = None
    lead_time_weeks: int | None = Field(default=None, ge=0, le=104)
    notes: str | None = None

    _s = field_validator("name", "supplier", "notes", mode="before")(_strip)


class TagCreate(_In):
    area_id: int
    quantity: Decimal | None = Field(default=None, ge=0)


class TagUpdate(_In):
    status: Literal["considering", "chosen", "declined"] | None = None
    reason: str | None = None
    quantity: Decimal | None = Field(default=None, ge=0)

    _s = field_validator("reason", mode="before")(_strip)


class SampleCreate(_In):
    description: str = Field(min_length=1)
    area_id: int | None = None
    candidate_id: int | None = None
    expect_reply_by: date | None = None
    notes: str | None = None


class SampleUpdate(_In):
    status: Literal["requested", "sent", "replied", "cancelled"] | None = None
    sent_on: date | None = None
    expect_reply_by: date | None = None
    notes: str | None = None


# ------------------------------------------------------------ timeline
class EventCreate(_In):
    kind: Literal["contact", "showroom_visit", "site_visit"]
    occurred_at: datetime | None = None
    channel: Literal["phone", "text", "email", "whatsapp", "in_person"] | None = None
    direction: Literal["in", "out"] | None = None
    showroom: str | None = None
    summary: str = Field(min_length=1)
    notes: str | None = None
    people: list[int] = []
    scheduled_visit_id: int | None = None
    # Every event produces a next step. No exception.
    next_step: NextStep

    _s = field_validator("summary", "notes", "showroom", mode="before")(_strip)


class VisitCreate(_In):
    kind: Literal["showroom", "site"] = "showroom"
    starts_at: datetime
    rep_id: int | None = None
    showroom: str | None = None
    purpose: str | None = None
    expected: str | None = None


class VisitResolve(_In):
    status: Literal["no_show", "cancelled"]
    note: str = Field(min_length=1)
    next_step: NextStep


class VisitReschedule(_In):
    starts_at: datetime
