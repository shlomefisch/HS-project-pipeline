from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..auth import admin, member, set_password
from ..db import get_db
from ..models import Job, Task, User
from ..rules.constants import CLASSES, SHOWROOMS
from ..passwords import problem_with
from ..schemas import PasswordSet, UserCreate, UserUpdate
from ..serialize import user_out
from ..services.jobs import refuse_nulls
from ..timeutil import now

router = APIRouter(prefix="/users", tags=["users"])


@router.get("")
def list_users(include_inactive: bool = False, db: Session = Depends(get_db), user: User = Depends(member)):
    stmt = select(User).order_by(User.name)
    if not include_inactive or not user.is_admin:
        stmt = stmt.where(User.active.is_(True))
    return [user_out(u) for u in db.scalars(stmt)]


@router.post("", status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db), _: User = Depends(admin)):
    """An admin adds a person with a temporary password; they pick their own on first sign-in."""
    email = (body.email or "").lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(422, "That doesn't look like an email address.")
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "Someone with that email is already on the team.")
    if body.home_showroom not in (None, *SHOWROOMS):
        raise HTTPException(422, "Unknown showroom.")
    if body.default_class not in (None, *CLASSES):
        raise HTTPException(422, "Unknown class.")
    problem = problem_with(body.password)
    if problem:
        raise HTTPException(422, problem)
    user = User(
        email=email,
        name=body.name,
        role=body.role,
        is_admin=body.is_admin,
        home_showroom=body.home_showroom,
        default_class=body.default_class,
        active=True,
    )
    set_password(user, body.password, must_change=True)
    db.add(user)
    db.commit()
    return user_out(user)


@router.post("/{user_id}/password")
def reset_password(user_id: int, body: PasswordSet, db: Session = Depends(get_db), me: User = Depends(admin)):
    """Forgotten password: the admin sets a temporary one. Their old sessions end."""
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "User not found.")
    if target.id == me.id:
        raise HTTPException(422, "Change your own password from the Today screen (bottom of the page).")
    problem = problem_with(body.password)
    if problem:
        raise HTTPException(422, problem)
    set_password(target, body.password, must_change=True)
    db.commit()
    return user_out(target)


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
    refuse_nulls(data, "name", "role", "is_admin", "active")
    if "home_showroom" in data and data["home_showroom"] not in (None, *SHOWROOMS):
        raise HTTPException(422, "Unknown showroom.")
    if "default_class" in data and data["default_class"] not in (None, *CLASSES):
        raise HTTPException(422, "Unknown class.")
    if target.id == me.id and data.get("is_admin") is False:
        raise HTTPException(422, "You can't remove your own admin rights.")
    if data.get("active") is False and target.active:
        # Nothing may be orphaned: every count on the Away or gone screen must be zero.
        from ..services import absences

        h = absences.holdings(db, target.id)
        left = [f"{len(h[k])} {label}" for k, label in (("jobs", "open job(s)"), ("tasks", "open task(s)"), ("visits", "upcoming visit(s)"), ("orders", "order(s) they handle")) if h[k]]
        if h["takeoff"]:
            left.append("the takeoff slot")
        if left:
            raise HTTPException(409, f"{target.name} still holds {', '.join(left)}. Hand them over on the Away or gone screen first.")
        covering = absences.covering_for_anyone(db, target.id)
        if covering:
            names = ", ".join(db.get(User, a.user_id).name for a in covering)
            raise HTTPException(409, f"{target.name} is the cover while {names} is away. Pick another cover first.")
        absences.release_on_deactivate(db, target.id)
    for k, v in data.items():
        setattr(target, k, v)
    db.commit()
    return user_out(target)
