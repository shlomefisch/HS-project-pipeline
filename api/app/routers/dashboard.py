"""Each role's first screen."""

from fastapi import APIRouter, Depends
from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from ..auth import member
from ..db import get_db
from ..models import Job, ScheduledVisit, Task, User
from ..rules.constants import TASK_OPEN
from ..serialize import row
from ..timeutil import day_bounds, now, today

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _with_job(rows) -> list[dict]:
    return [{**row(t), "job_name": j.name, "job_rep_id": j.rep_id} for t, j in rows]


@router.get("/rep")
def rep_view(rep_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(member)):
    """Went wrong → today's visits → due and overdue → stuck jobs. Counts show even at zero."""
    rid = rep_id or user.id
    t0 = today()
    start, end = day_bounds(t0)

    went_wrong = db.execute(
        select(Task, Job).join(Job, Job.id == Task.job_id)
        .where(
            Job.rep_id == rid,
            or_(Task.needs_rep_attention.is_(True), Task.status == "blocked"),
        )
        .order_by(Task.due_date)
    ).all()

    visits = db.execute(
        select(ScheduledVisit, Job).join(Job, Job.id == ScheduledVisit.job_id)
        .where(
            ScheduledVisit.rep_id == rid,
            ScheduledVisit.status == "scheduled",
            ScheduledVisit.starts_at >= start,
            ScheduledVisit.starts_at < end,
        )
        .order_by(ScheduledVisit.starts_at)
    ).all()

    due = db.execute(
        select(Task, Job).join(Job, Job.id == Task.job_id)
        .where(Task.assignee_id == rid, Task.status.in_(TASK_OPEN), Task.due_date <= t0)
        .order_by(Task.due_date, Task.id)
    ).all()

    has_open = exists().where(Task.job_id == Job.id, Task.status.in_(TASK_OPEN))
    stuck_jobs = list(
        db.scalars(select(Job).where(Job.rep_id == rid, Job.status == "active", ~has_open).order_by(Job.created_at))
    )
    missed_visits = db.execute(
        select(ScheduledVisit, Job).join(Job, Job.id == ScheduledVisit.job_id)
        .where(ScheduledVisit.rep_id == rid, ScheduledVisit.status == "scheduled", ScheduledVisit.starts_at < now())
        .where(ScheduledVisit.starts_at < start)
        .order_by(ScheduledVisit.starts_at)
    ).all()

    return {
        "today": t0.isoformat(),
        "went_wrong": _with_job(went_wrong),
        "visits_today": [{**row(v), "job_name": j.name} for v, j in visits],
        "due": [{**d, "overdue": d["due_date"] < t0.isoformat()} for d in _with_job(due)],
        "stuck": {
            "jobs": [row(j) for j in stuck_jobs],
            "missed_visits": [{**row(v), "job_name": j.name} for v, j in missed_visits],
        },
        "counts": {
            "went_wrong": len(went_wrong),
            "visits_today": len(visits),
            "due": len(due),
            "stuck": len(stuck_jobs) + len(missed_visits),
        },
    }


@router.get("/office")
def office_view(db: Session = Depends(get_db), user: User = Depends(member)):
    """Back office: own tasks first, by due date."""
    rows = db.execute(
        select(Task, Job).join(Job, Job.id == Task.job_id)
        .where(Task.assignee_id == user.id, Task.status.in_(TASK_OPEN))
        .order_by(Task.due_date, Task.id)
    ).all()
    t0 = today().isoformat()
    tasks = [{**d, "overdue": d["due_date"] < t0} for d in _with_job(rows)]
    return {"today": t0, "tasks": tasks, "counts": {"tasks": len(tasks), "overdue": sum(1 for t in tasks if t["overdue"])}}
