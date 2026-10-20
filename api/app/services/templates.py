"""Step templates: at set moments the job gets its usual steps by itself.

Moments: job created, takeoff done, estimate started, area decided.
Each template step names who does it (the rep, the takeoff person, whoever
triggered the moment, or a named person), when it's due and how loud it is.
A step already open on the job with the same title isn't added twice.
"""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AppSetting, Area, Job, StepTemplate, Task, User
from ..rules.constants import PLAYBOOK_FOR_TYPE, TASK_OPEN
from ..schemas import NextStep
from ..timeutil import today

TRIGGERS = {
    "job_created": "Job created",
    "takeoff_done": "Takeoff done",
    "estimate_started": "Estimate started",
    "area_decided": "Area decided",
    "order_placed": "Order placed (estimate sent)",
    "order_approved": "Order approved — sales order made",
    "order_delivery": "Ready for delivery",
    "order_closing": "Delivered — closing",
}
PLAYBOOKS = {"all": "Every job", "single_family": "Single-family", "projects": "Projects (multi-unit, commercial, …)"}
ASSIGNEE_KINDS = {
    "rep": "The job's rep",
    "handler": "The order's handler (falls back to the rep)",
    "takeoff": "The takeoff person",
    "actor": "Whoever did it",
    "user": "A named person",
}


def _usable(db: Session, user_id: int | None) -> bool:
    if user_id is None:
        return False
    u = db.get(User, user_id)
    return bool(u and u.active and u.role not in ("pending", "viewer"))


def _who(db: Session, step: StepTemplate, job: Job, by: User, order=None) -> int:
    if step.assignee_kind == "handler":
        uid = order.handler_id if order is not None and order.handler_id else job.rep_id
    elif step.assignee_kind == "takeoff":
        s = db.get(AppSetting, "takeoff_user_id")
        uid = int(s.value) if s and s.value and s.value.isdigit() else None
    elif step.assignee_kind == "actor":
        uid = by.id
    elif step.assignee_kind == "user":
        uid = step.assignee_user_id
    else:
        uid = job.rep_id
    # Nobody usable (left, not set): the rep, who owns the job, gets it rather than nobody.
    return uid if _usable(db, uid) else job.rep_id


def apply(db: Session, job: Job, trigger: str, by: User, area: Area | None = None, order=None) -> list[Task]:
    from .tasks import create_task

    if job.status != "active":
        return []
    playbook = PLAYBOOK_FOR_TYPE.get(job.project_type or "")
    books = ("all", playbook) if playbook else ("all",)
    steps = db.scalars(
        select(StepTemplate).where(StepTemplate.trigger == trigger, StepTemplate.active.is_(True), StepTemplate.playbook.in_(books))
        .order_by(StepTemplate.sort_order, StepTemplate.id)
    ).all()
    made = []
    for st in steps:
        title = f"{st.title} — {area.name}" if area is not None else st.title
        exists = db.scalar(select(Task.id).where(Task.job_id == job.id, Task.title == title, Task.status.in_(TASK_OPEN)))
        if exists:
            continue
        task = create_task(
            db, job,
            NextStep(title=title, assignee_id=_who(db, st, job, by, order), due_date=today() + timedelta(days=st.due_days),
                     severity=st.severity, notes=st.notes, area_id=area.id if area is not None else None),
            by,
        )
        task.template_step_id = st.id
        if order is not None:
            task.order_id = order.id
        made.append(task)
    return made
