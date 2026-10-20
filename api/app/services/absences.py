"""Away or gone.

Away: from/until dates and a cover. While it runs, everything the person holds —
jobs, open tasks, upcoming visits, the takeoff slot — sits with the cover, marked
"covering for", and anything new aimed at them goes to the cover too. On return,
open work goes back automatically; finished work stays credited to the cover.

Gone: everything is handed over, in bulk or one by one; only then can the
account be deactivated. History keeps the name either way.
"""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Absence, AppSetting, Job, ScheduledVisit, Task, User
from ..rules.constants import TASK_OPEN
from ..timeutil import now, today

OPEN_JOBS = ("active", "on_hold")


# ------------------------------------------------------------- routing
def current(db: Session, user_id: int) -> Absence | None:
    return db.scalar(select(Absence).where(Absence.user_id == user_id, Absence.status == "active"))


def route(db: Session, user_id: int) -> tuple[int, int | None]:
    """Who actually gets work aimed at user_id: (who, covering_for or None)."""
    a = current(db, user_id)
    if a is None or not _usable(db, a.cover_id):
        return user_id, None
    # A cover who is away themselves passes it on once more — never loops.
    b = current(db, a.cover_id)
    if b is not None and b.cover_id != user_id and _usable(db, b.cover_id):
        return b.cover_id, user_id
    return a.cover_id, user_id


def _usable(db: Session, user_id: int) -> bool:
    u = db.get(User, user_id)
    return bool(u and u.active and u.role not in ("pending", "viewer"))


# ------------------------------------------------------------ holdings
def holdings(db: Session, user_id: int) -> dict:
    """Everything this person holds right now."""
    jobs = list(db.scalars(select(Job).where(Job.rep_id == user_id, Job.status.in_(OPEN_JOBS)).order_by(Job.name)))
    tasks = list(db.scalars(select(Task).where(Task.assignee_id == user_id, Task.status.in_(TASK_OPEN)).order_by(Task.due_date)))
    visits = list(db.scalars(
        select(ScheduledVisit).where(ScheduledVisit.rep_id == user_id, ScheduledVisit.status == "scheduled", ScheduledVisit.starts_at >= now())
        .order_by(ScheduledVisit.starts_at)
    ))
    slot = db.get(AppSetting, "takeoff_user_id")
    return {"jobs": jobs, "tasks": tasks, "visits": visits, "takeoff": bool(slot and slot.value == str(user_id))}


def _set_takeoff(db: Session, user_id: int | None) -> None:
    s = db.get(AppSetting, "takeoff_user_id") or AppSetting(key="takeoff_user_id")
    s.value = str(user_id) if user_id is not None else None
    s.updated_at = now()
    db.add(s)


# ------------------------------------------------------------- away
def _check_cover(db: Session, user_id: int, cover_id: int) -> User:
    if cover_id == user_id:
        raise HTTPException(422, "Someone can't cover for themselves.")
    cover = db.get(User, cover_id)
    if cover is None or not cover.active or cover.role in ("pending", "viewer"):
        raise HTTPException(422, "The cover must be an active user who can do the work.")
    if current(db, cover_id) is not None:
        raise HTTPException(422, f"{cover.name} is away too. Pick someone who's in.")
    return cover


def plan(db: Session, user: User, cover_id: int, starts_on, ends_on, note: str | None, by: User) -> Absence:
    if ends_on < starts_on:
        raise HTTPException(422, "Back can't be before away.")
    if ends_on < today():
        raise HTTPException(422, "That's all in the past.")
    _check_cover(db, user.id, cover_id)
    if db.scalar(select(Absence.id).where(Absence.user_id == user.id, Absence.status.in_(("planned", "active")))):
        raise HTTPException(409, f"{user.name} already has an away set. Change or end that one first.")
    a = Absence(user_id=user.id, cover_id=cover_id, starts_on=starts_on, ends_on=ends_on, note=note, status="planned", created_by=by.id)
    db.add(a)
    db.flush()
    if starts_on <= today():
        start(db, a)
    return a


def start(db: Session, a: Absence) -> None:
    """Hands everything to the cover, remembered as covering for."""
    h = holdings(db, a.user_id)
    # Something they were already covering for someone else keeps that someone,
    # so it still goes home to its owner when the owner is back.
    for j in h["jobs"]:
        j.rep_id, j.covering_for_id = a.cover_id, j.covering_for_id or a.user_id
    for t in h["tasks"]:
        t.assignee_id, t.covering_for_id = a.cover_id, t.covering_for_id or a.user_id
    for v in h["visits"]:
        v.rep_id, v.covering_for_id = a.cover_id, v.covering_for_id or a.user_id
    if h["takeoff"]:
        _set_takeoff(db, a.cover_id)
        a.took_takeoff = True
    a.status, a.started_at = "active", now()


def end(db: Session, a: Absence) -> None:
    """They're back: open work returns; finished work stays with whoever did it."""
    if a.status == "planned":
        a.status, a.ended_at = "cancelled", now()
        return
    if a.status != "active":
        return
    uid = a.user_id
    # Whoever holds it now — the cover, or the cover's own cover — it goes home.
    # (A deliberate hand-over or rep change clears covering_for, so those stay put.)
    for j in db.scalars(select(Job).where(Job.covering_for_id == uid)):
        if j.status in OPEN_JOBS:
            j.rep_id = uid
        j.covering_for_id = None
    for t in db.scalars(select(Task).where(Task.covering_for_id == uid, Task.status.in_(TASK_OPEN))):
        t.assignee_id, t.covering_for_id = uid, None  # done ones keep the cover's name and the note
    for v in db.scalars(select(ScheduledVisit).where(ScheduledVisit.covering_for_id == uid, ScheduledVisit.status == "scheduled")):
        if v.starts_at >= now():
            v.rep_id, v.covering_for_id = uid, None
    if a.took_takeoff:
        slot = db.get(AppSetting, "takeoff_user_id")
        chain = {str(a.cover_id)}
        b = current(db, a.cover_id)
        if b is not None:
            chain.add(str(b.cover_id))
        if slot and slot.value in chain:
            _set_takeoff(db, uid)
    a.status, a.ended_at = "ended", now()


def apply_due(db: Session) -> int:
    """Starts aways whose day has come and ends those that are over. Safe to run any time."""
    n = 0
    t0 = today()
    for a in db.scalars(select(Absence).where(Absence.status == "planned", Absence.starts_on <= t0)).all():
        if a.ends_on < t0:
            a.status, a.ended_at = "cancelled", now()
        elif current(db, a.cover_id) is None:
            start(db, a)
        n += 1
    for a in db.scalars(select(Absence).where(Absence.status == "active", Absence.ends_on < t0)).all():
        end(db, a)
        n += 1
    return n


# ------------------------------------------------------------- gone
def hand_over(db: Session, user_id: int, to_id: int, what: str, ids: list[int] | None) -> int:
    """Reassigns jobs / tasks / visits / the takeoff slot. ids=None means all of that kind."""
    _check_cover(db, user_id, to_id)
    h = holdings(db, user_id)
    if what == "takeoff":
        if h["takeoff"]:
            _set_takeoff(db, to_id)
            return 1
        return 0
    items = h[what]
    if ids is not None:
        wanted = set(ids)
        items = [x for x in items if x.id in wanted]
    for x in items:
        if what == "jobs":
            x.rep_id, x.covering_for_id = to_id, None
        elif what == "tasks":
            x.assignee_id, x.covering_for_id = to_id, None
        else:
            x.rep_id, x.covering_for_id = to_id, None
    return len(items)


def covering_for_anyone(db: Session, user_id: int) -> list[Absence]:
    return list(db.scalars(select(Absence).where(Absence.cover_id == user_id, Absence.status.in_(("planned", "active")))))


def release_on_deactivate(db: Session, user_id: int) -> None:
    """Someone leaving while away: their cover keeps what they hold, for good."""
    a = current(db, user_id) or db.scalar(select(Absence).where(Absence.user_id == user_id, Absence.status == "planned"))
    if a is None:
        return
    for model in (Job, Task, ScheduledVisit):
        for x in db.scalars(select(model).where(model.covering_for_id == user_id)):
            x.covering_for_id = None
    a.status, a.ended_at = ("ended" if a.status == "active" else "cancelled"), now()
