"""Away or gone — one admin screen per person."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import admin
from ..db import get_db
from ..models import Absence, Job, User
from ..schemas import _In, _strip
from ..serialize import row, user_out
from ..services import absences as A

router = APIRouter(tags=["team"])


class AwayCreate(_In):
    cover_id: int
    starts_on: date
    ends_on: date
    note: str | None = None

    _s = field_validator("note", mode="before")(_strip)


class HandOver(_In):
    to_user_id: int
    what: str = Field(pattern="^(jobs|tasks|visits|takeoff)$")
    ids: list[int] | None = None  # None = all of that kind


def _user(db: Session, user_id: int) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "User not found.")
    return u


def _screen(db: Session, u: User) -> dict:
    A.apply_due(db)
    db.commit()
    h = A.holdings(db, u.id)
    job_names = {j.id: j.name for j in db.scalars(select(Job).where(Job.id.in_([t.job_id for t in h["tasks"]] + [v.job_id for v in h["visits"]])))} if (h["tasks"] or h["visits"]) else {}
    absences = list(db.scalars(select(Absence).where(Absence.user_id == u.id).order_by(Absence.starts_on.desc()).limit(10)))
    covering = list(db.scalars(select(Absence).where(Absence.cover_id == u.id, Absence.status == "active")))
    return {
        "user": user_out(u),
        "holds": {
            "jobs": [{**row(j), "label": j.name} for j in h["jobs"]],
            "tasks": [{**row(t), "label": t.title, "job_name": job_names.get(t.job_id)} for t in h["tasks"]],
            "visits": [{**row(v), "label": f"{v.kind} visit", "job_name": job_names.get(v.job_id)} for v in h["visits"]],
            "takeoff": h["takeoff"],
        },
        "counts": {"jobs": len(h["jobs"]), "tasks": len(h["tasks"]), "visits": len(h["visits"]), "takeoff": int(h["takeoff"])},
        "current": next((row(a) for a in absences if a.status in ("planned", "active")), None),
        "history": [row(a) for a in absences if a.status not in ("planned", "active")],
        "covering_for": [a.user_id for a in covering],
    }


@router.get("/users/{user_id}/away-or-gone")
def screen(user_id: int, db: Session = Depends(get_db), _: User = Depends(admin)):
    return _screen(db, _user(db, user_id))


@router.post("/users/{user_id}/away", status_code=201)
def set_away(user_id: int, body: AwayCreate, db: Session = Depends(get_db), me: User = Depends(admin)):
    u = _user(db, user_id)
    if not u.active:
        raise HTTPException(409, "This account is deactivated.")
    A.plan(db, u, body.cover_id, body.starts_on, body.ends_on, body.note, me)
    db.commit()
    return _screen(db, u)


@router.post("/users/{user_id}/back")
def back_now(user_id: int, db: Session = Depends(get_db), _: User = Depends(admin)):
    """Back early, or cancel an away that hasn't started."""
    u = _user(db, user_id)
    a = db.scalar(select(Absence).where(Absence.user_id == u.id, Absence.status.in_(("planned", "active"))))
    if a is None:
        raise HTTPException(409, f"{u.name} isn't set as away.")
    A.end(db, a)
    db.commit()
    return _screen(db, u)


@router.post("/users/{user_id}/hand-over")
def hand_over(user_id: int, body: HandOver, db: Session = Depends(get_db), _: User = Depends(admin)):
    u = _user(db, user_id)
    A.hand_over(db, u.id, body.to_user_id, body.what, body.ids)
    db.commit()
    return _screen(db, u)
