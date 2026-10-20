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


# ---------------------------------------------------------- management
QUIET_DAYS = 14  # a job with nothing logged or changed this long is "quiet"
LOSS_WINDOW_DAYS = 90


@router.get("/management")
def management_view(db: Session = Depends(get_db), user: User = Depends(member)):
    """Across everyone: where the jobs stand, who is behind, what has gone quiet, why jobs are lost."""
    from datetime import timedelta

    from fastapi import HTTPException
    from sqlalchemy import func

    from ..models import Absence, AuditLog

    if not (user.is_admin or user.role == "management"):
        raise HTTPException(403, "Management only.")
    t0 = today()

    by_class: dict[str, dict[str, int]] = {}
    for cls, status, n in db.execute(select(Job.class_code, Job.status, func.count()).group_by(Job.class_code, Job.status)):
        by_class.setdefault(cls, {"active": 0, "on_hold": 0, "lost": 0, "closed": 0})[status] = n

    users = {u.id: u for u in db.scalars(select(User).where(User.active.is_(True), User.role.notin_(("pending", "viewer"))))}
    people = {
        uid: {"user_id": uid, "name": u.name, "role": u.role, "open": 0, "overdue": 0, "jobs": 0, "stuck": 0, "went_wrong": 0}
        for uid, u in users.items()
    }
    for uid, open_n, overdue_n in db.execute(
        select(Task.assignee_id, func.count(), func.count().filter(Task.due_date < t0))
        .where(Task.status.in_(TASK_OPEN)).group_by(Task.assignee_id)
    ):
        if uid in people:
            people[uid]["open"], people[uid]["overdue"] = open_n, overdue_n
    has_open = exists().where(Task.job_id == Job.id, Task.status.in_(TASK_OPEN))
    for rid, n, stuck in db.execute(
        select(Job.rep_id, func.count(), func.count().filter(~has_open))
        .where(Job.status == "active").group_by(Job.rep_id)
    ):
        if rid in people:
            people[rid]["jobs"], people[rid]["stuck"] = n, stuck
    for rid, n in db.execute(
        select(Job.rep_id, func.count()).join(Task, Task.job_id == Job.id)
        .where(or_(Task.needs_rep_attention.is_(True), Task.status == "blocked")).group_by(Job.rep_id)
    ):
        if rid in people:
            people[rid]["went_wrong"] = n

    last = select(AuditLog.job_id, func.max(AuditLog.at).label("last_at")).where(AuditLog.job_id.is_not(None)).group_by(AuditLog.job_id).subquery()
    cutoff = now() - timedelta(days=QUIET_DAYS)
    quiet = db.execute(
        select(Job, last.c.last_at).join(last, last.c.job_id == Job.id)
        .where(Job.status == "active", last.c.last_at < cutoff).order_by(last.c.last_at)
    ).all()

    since = now() - timedelta(days=LOSS_WINDOW_DAYS)
    lost_at = (
        select(AuditLog.job_id, func.max(AuditLog.at).label("at"))
        .where(AuditLog.table_name == "jobs", AuditLog.changes.has_key("status")).group_by(AuditLog.job_id).subquery()
    )
    losses: dict[str, int] = {}
    for reason, n in db.execute(
        select(Job.lost_reason, func.count()).join(lost_at, lost_at.c.job_id == Job.id)
        .where(Job.status == "lost", lost_at.c.at >= since).group_by(Job.lost_reason)
    ):
        losses[reason or "other"] = n

    away = db.scalars(select(Absence).where(Absence.status == "active").order_by(Absence.ends_on)).all()

    return {
        "today": t0.isoformat(),
        "quiet_days": QUIET_DAYS,
        "loss_window_days": LOSS_WINDOW_DAYS,
        "by_class": by_class,
        "people": sorted(people.values(), key=lambda p: (-p["overdue"], -p["went_wrong"], -p["stuck"], p["name"])),
        "quiet": [{"id": j.id, "name": j.name, "rep_id": j.rep_id, "class_code": j.class_code, "last_at": at.isoformat()} for j, at in quiet],
        "losses": losses,
        "away": [{"user_id": a.user_id, "cover_id": a.cover_id, "ends_on": a.ends_on.isoformat()} for a in away],
        "totals": {
            "active": sum(c["active"] for c in by_class.values()),
            "overdue": sum(p["overdue"] for p in people.values()),
            "went_wrong": sum(p["went_wrong"] for p in people.values()),
            "quiet": len(quiet),
        },
    }
