from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..auth import admin, member
from ..db import get_db
from ..models import Job, Task, User
from ..rules.constants import CLASSES, SHOWROOMS
from ..schemas import UserUpdate
from ..serialize import user_out
from ..timeutil import now

router = APIRouter(prefix="/users", tags=["users"])


@router.get("")
def list_users(include_inactive: bool = False, db: Session = Depends(get_db), user: User = Depends(member)):
    stmt = select(User).order_by(User.name)
    if not include_inactive or not user.is_admin:
        stmt = stmt.where(User.active.is_(True))
    return [user_out(u) for u in db.scalars(stmt)]


@router.get("/assignee-suggestions")
def assignee_suggestions(db: Session = Depends(get_db), user: User = Depends(member)):
    """The three people this person assigns work to most, recent weeks counting double."""
    recent = now() - timedelta(days=60)
    weight = func.sum(case((Task.created_at >= recent, 2), else_=1))
    stmt = (
        select(Task.assignee_id, weight.label("w"))
        .join(User, User.id == Task.assignee_id)
        .where(Task.created_by == user.id, User.active.is_(True), User.role != "pending")
        .group_by(Task.assignee_id)
        .order_by(weight.desc())
        .limit(3)
    )
    ids = [r.assignee_id for r in db.execute(stmt)]
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}
    return [user_out(users[i]) for i in ids if i in users]


@router.patch("/{user_id}")
def update_user(user_id: int, body: UserUpdate, db: Session = Depends(get_db), me: User = Depends(admin)):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "User not found.")
    data = body.model_dump(exclude_unset=True)
    if "home_showroom" in data and data["home_showroom"] not in (None, *SHOWROOMS):
        raise HTTPException(422, "Unknown showroom.")
    if "default_class" in data and data["default_class"] not in (None, *CLASSES):
        raise HTTPException(422, "Unknown class.")
    if target.id == me.id and data.get("is_admin") is False:
        raise HTTPException(422, "You can't remove your own admin rights.")
    if data.get("active") is False:
        # Away/gone screen comes later; until then, refuse to orphan live work.
        open_tasks = db.scalar(
            select(func.count()).select_from(Task).where(Task.assignee_id == target.id, Task.status.in_(("open", "blocked")))
        )
        if open_tasks:
            raise HTTPException(409, f"{target.name} still has {open_tasks} open task(s). Reassign them first.")
        owned = db.scalar(
            select(func.count()).select_from(Job).where(Job.rep_id == target.id, Job.status.in_(("active", "on_hold")))
        )
        if owned:
            raise HTTPException(409, f"{target.name} is still the rep on {owned} open job(s). Reassign them first.")
    for k, v in data.items():
        setattr(target, k, v)
    db.commit()
    return user_out(target)
