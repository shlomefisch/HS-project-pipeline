"""The loop: every next step has a named person and a date, and nothing goes quiet."""

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Area, Job, Task, User
from ..rules.constants import TASK_OPEN
from ..schemas import NextStep
from ..timeutil import now


def active_user(db: Session, user_id: int, what: str = "assignee") -> User:
    user = db.get(User, user_id)
    if user is None or not user.active or user.role == "pending":
        raise HTTPException(422, f"The {what} must be an active, set-up user.")
    return user


def open_task_count(db: Session, job_id: int, exclude_task_id: int | None = None) -> int:
    stmt = select(func.count()).select_from(Task).where(Task.job_id == job_id, Task.status.in_(TASK_OPEN))
    if exclude_task_id:
        stmt = stmt.where(Task.id != exclude_task_id)
    return db.scalar(stmt) or 0


def create_task(
    db: Session,
    job: Job,
    step: NextStep,
    by: User,
    parent_task_id: int | None = None,
    source_event_id: int | None = None,
) -> Task:
    active_user(db, step.assignee_id)
    if step.area_id is not None:
        area = db.get(Area, step.area_id)
        if area is None or area.job_id != job.id:
            raise HTTPException(422, "That area isn't on this job.")
    task = Task(
        job_id=job.id,
        area_id=step.area_id,
        title=step.title.strip(),
        notes=step.notes,
        assignee_id=step.assignee_id,
        due_date=step.due_date,
        severity=step.severity,
        status="open",
        created_by=by.id,
        parent_task_id=parent_task_id,
        source_event_id=source_event_id,
    )
    db.add(task)
    db.flush()
    return task


def complete(db: Session, task: Task, outcome: str, note: str | None, step: NextStep | None, by: User) -> Task | None:
    """Closes out a task. Returns the follow-up task if one was created.

    done / skipped  -> a next step is required unless the job already has other open work
    bad_answer      -> a note and a next step are required: bad news must land on someone
    blocked         -> a note is required; the task stays open, flagged for the rep
    """
    if task.status not in TASK_OPEN:
        raise HTTPException(409, "This task is already closed.")
    job = db.get(Job, task.job_id)
    is_rep = by.id == job.rep_id

    if outcome in ("blocked", "bad_answer", "skipped") and not note:
        raise HTTPException(422, "Say what happened — a note is required.")

    if outcome == "blocked":
        task.status = "blocked"
        task.outcome_note = note
        task.needs_rep_attention = not is_rep
        if step is not None:
            return create_task(db, job, step, by, parent_task_id=task.id)
        return None

    if task.kind == "takeoff" and outcome == "done":
        areas = list(db.scalars(select(Area).where(Area.job_id == job.id, Area.status.in_(("open", "decided")))))
        if not areas:
            raise HTTPException(422, "Add the job's areas first — the takeoff gives each one its footage.")
        missing = [a.name for a in areas if a.footage is None]
        if missing:
            raise HTTPException(422, "The takeoff isn't done until every area has footage. Still missing: " + ", ".join(missing) + ".")

    if outcome == "bad_answer" and step is None:
        raise HTTPException(422, "A bad answer needs a next step — usually the rep calling the customer.")

    if outcome in ("done", "skipped") and step is None and job.status == "active":
        if open_task_count(db, job.id, exclude_task_id=task.id) == 0:
            raise HTTPException(
                422,
                "This is the job's last open step. Add the next step — who does what, by when — "
                "or the job goes quiet.",
            )

    task.status = outcome
    task.outcome_note = note
    task.completed_at = now()
    task.completed_by = by.id
    task.needs_rep_attention = outcome == "bad_answer" and not is_rep

    if step is not None:
        return create_task(db, job, step, by, parent_task_id=task.id)
    return None
