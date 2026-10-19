from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import member, writer
from ..db import get_db
from ..models import Job, Task, User
from ..rules.constants import TASK_OPEN
from ..schemas import TaskComplete, TaskCreate, TaskUpdate
from ..serialize import row
from ..services.jobs import get_job
from ..services.tasks import active_user, complete, create_task

router = APIRouter(tags=["tasks"])


def _task(db: Session, task_id: int) -> Task:
    t = db.get(Task, task_id)
    if t is None:
        raise HTTPException(404, "Task not found.")
    return t


@router.post("/jobs/{job_id}/tasks", status_code=201)
def add_task(job_id: int, body: TaskCreate, db: Session = Depends(get_db), user: User = Depends(writer)):
    """A step the template never knew about. Same rules: a name and a date."""
    job = get_job(db, job_id)
    t = create_task(db, job, body, user)
    db.commit()
    return row(t)


@router.patch("/tasks/{task_id}")
def update_task(task_id: int, body: TaskUpdate, db: Session = Depends(get_db), _: User = Depends(writer)):
    t = _task(db, task_id)
    if t.status not in TASK_OPEN:
        raise HTTPException(409, "This task is closed.")
    data = body.model_dump(exclude_unset=True)
    if "title" in data and not (data["title"] or "").strip():
        raise HTTPException(422, "A task needs a title.")
    if data.get("assignee_id") is not None:
        active_user(db, data["assignee_id"])
    if "due_date" in data and data["due_date"] is None:
        raise HTTPException(422, "A task can't lose its due date.")
    if "assignee_id" in data and data["assignee_id"] is None:
        raise HTTPException(422, "A task can't lose its assignee.")
    for k, v in data.items():
        setattr(t, k, v)
    db.commit()
    return row(t)


@router.post("/tasks/{task_id}/complete")
def complete_task(task_id: int, body: TaskComplete, db: Session = Depends(get_db), user: User = Depends(writer)):
    t = _task(db, task_id)
    follow_up = complete(db, t, body.outcome, body.note, body.next_step, user)
    db.commit()
    return {"task": row(t), "next_task": row(follow_up)}


@router.post("/tasks/{task_id}/reopen")
def reopen_task(task_id: int, db: Session = Depends(get_db), _: User = Depends(writer)):
    """Unblock: the task goes back to open."""
    t = _task(db, task_id)
    if t.status != "blocked":
        raise HTTPException(409, "Only a blocked task can be reopened.")
    t.status, t.needs_rep_attention = "open", False
    db.commit()
    return row(t)


@router.post("/tasks/{task_id}/acknowledge")
def acknowledge(task_id: int, db: Session = Depends(get_db), user: User = Depends(writer)):
    """The rep has seen the bad news. It leaves his 'went wrong' list."""
    t = _task(db, task_id)
    job = db.get(Job, t.job_id)
    if user.id != job.rep_id and not user.is_admin:
        raise HTTPException(403, "Only the job's rep can acknowledge this.")
    t.needs_rep_attention = False
    db.commit()
    return row(t)


@router.get("/tasks")
def my_tasks(
    assignee_id: int | None = None,
    include_closed: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(member),
):
    stmt = select(Task, Job).join(Job, Job.id == Task.job_id).where(Task.assignee_id == (assignee_id or user.id))
    if not include_closed:
        stmt = stmt.where(Task.status.in_(TASK_OPEN))
    rows = db.execute(stmt.order_by(Task.due_date, Task.id).limit(500)).all()
    return [{**row(t), "job_name": j.name, "job_rep_id": j.rep_id} for t, j in rows]
