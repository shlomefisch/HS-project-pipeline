"""Editing the step templates (admins)."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import admin, member
from ..db import get_db
from ..models import StepTemplate, User
from ..schemas import _In, _strip
from ..serialize import row
from ..services.templates import ASSIGNEE_KINDS, PLAYBOOKS, TRIGGERS, _usable

router = APIRouter(prefix="/templates", tags=["templates"])

Trigger = Literal["job_created", "takeoff_done", "estimate_started", "area_decided"]
Playbook = Literal["all", "single_family", "projects"]
Kind = Literal["rep", "takeoff", "actor", "user"]
Severity = Literal["silent", "notify", "interrupt"]


class StepIn(_In):
    trigger: Trigger
    playbook: Playbook = "all"
    title: str = Field(min_length=1)
    notes: str | None = None
    assignee_kind: Kind = "rep"
    assignee_user_id: int | None = None
    due_days: int = Field(default=1, ge=0, le=365)
    severity: Severity = "silent"
    sort_order: int = 0

    _s = field_validator("title", "notes", mode="before")(_strip)


class StepPatch(_In):
    trigger: Trigger | None = None
    playbook: Playbook | None = None
    title: str | None = None
    notes: str | None = None
    assignee_kind: Kind | None = None
    assignee_user_id: int | None = None
    due_days: int | None = Field(default=None, ge=0, le=365)
    severity: Severity | None = None
    sort_order: int | None = None
    active: bool | None = None

    _s = field_validator("title", "notes", mode="before")(_strip)


def _check(db: Session, kind: str, user_id: int | None) -> None:
    if kind == "user" and not _usable(db, user_id):
        raise HTTPException(422, "Pick the person — an active user who can do the work.")


@router.get("")
def list_steps(db: Session = Depends(get_db), _: User = Depends(member)):
    steps = db.scalars(select(StepTemplate).where(StepTemplate.active.is_(True)).order_by(StepTemplate.trigger, StepTemplate.sort_order, StepTemplate.id))
    return {"steps": [row(s) for s in steps], "triggers": TRIGGERS, "playbooks": PLAYBOOKS, "assignee_kinds": ASSIGNEE_KINDS}


@router.post("", status_code=201)
def add_step(body: StepIn, db: Session = Depends(get_db), me: User = Depends(admin)):
    _check(db, body.assignee_kind, body.assignee_user_id)
    data = body.model_dump()
    if data["assignee_kind"] != "user":
        data["assignee_user_id"] = None
    s = StepTemplate(**data, created_by=me.id)
    db.add(s)
    db.commit()
    return row(s)


@router.patch("/{step_id}")
def edit_step(step_id: int, body: StepPatch, db: Session = Depends(get_db), _: User = Depends(admin)):
    s = db.get(StepTemplate, step_id)
    if s is None:
        raise HTTPException(404, "Step not found.")
    data = body.model_dump(exclude_unset=True)
    for key in ("trigger", "playbook", "title", "assignee_kind", "due_days", "severity", "sort_order", "active"):
        if key in data and data[key] is None:
            raise HTTPException(422, f"{key.replace('_', ' ').capitalize()} can't be empty.")
    kind = data.get("assignee_kind", s.assignee_kind)
    uid = data.get("assignee_user_id", s.assignee_user_id)
    _check(db, kind, uid)
    if kind != "user":
        data["assignee_user_id"] = None
    for k, v in data.items():
        setattr(s, k, v)
    db.commit()
    return row(s)
