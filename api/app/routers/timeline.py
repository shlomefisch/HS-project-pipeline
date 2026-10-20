"""Things that happened (events) and things that are booked to happen (scheduled visits)."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import member, writer
from ..db import get_db
from ..models import Event, EventPerson, Job, ScheduledVisit, User
from ..rules.constants import SHOWROOMS
from ..schemas import EventCreate, VisitCreate, VisitReschedule, VisitResolve
from ..serialize import row, user_out
from ..services.jobs import check_rep, get_job, live_entity
from ..services.tasks import create_task
from ..timeutil import day_bounds, now, today

router = APIRouter(tags=["timeline"])

_VISIT_EVENT = {"showroom": "showroom_visit", "site": "site_visit"}


def _check_showroom(showroom: str | None) -> None:
    if showroom is not None and showroom not in SHOWROOMS:
        raise HTTPException(422, f"Unknown showroom: {showroom}")


# -------------------------------------------------------------- events
@router.post("/jobs/{job_id}/events", status_code=201)
def log_event(job_id: int, body: EventCreate, db: Session = Depends(get_db), user: User = Depends(writer)):
    """Log a call, a visit, a site visit. Every one ends with a next step."""
    job = get_job(db, job_id)
    _check_showroom(body.showroom)
    if body.occurred_at is not None and body.occurred_at.tzinfo is None:
        raise HTTPException(422, "The time must include a time zone.")

    visit = None
    if body.scheduled_visit_id is not None:
        visit = db.get(ScheduledVisit, body.scheduled_visit_id)
        if visit is None or visit.job_id != job.id:
            raise HTTPException(422, "That visit isn't on this job.")
        if visit.status != "scheduled":
            raise HTTPException(409, f"That visit is already {visit.status.replace('_', ' ')}.")

    showroom = body.showroom
    if showroom is None and body.kind == "showroom_visit":
        showroom = (visit.showroom if visit else None) or user.home_showroom

    ev = Event(
        job_id=job.id,
        kind=body.kind,
        occurred_at=body.occurred_at or now(),
        channel=body.channel,
        direction=body.direction,
        showroom=showroom,
        summary=body.summary,
        notes=body.notes,
        scheduled_visit_id=visit.id if visit else None,
        logged_by=user.id,
    )
    db.add(ev)
    db.flush()
    for eid in {live_entity(db, i).id for i in body.people}:
        db.add(EventPerson(event_id=ev.id, entity_id=eid))

    if visit is not None:
        visit.status, visit.resolved_at, visit.resolved_by = "happened", now(), user.id

    create_task(db, job, body.next_step, user, source_event_id=ev.id)
    db.commit()
    return row(ev)


@router.get("/jobs/{job_id}/events")
def list_events(job_id: int, db: Session = Depends(get_db), _: User = Depends(member)):
    get_job(db, job_id)
    events = list(db.scalars(select(Event).where(Event.job_id == job_id).order_by(Event.occurred_at.desc())))
    people = db.execute(select(EventPerson).where(EventPerson.event_id.in_([e.id for e in events]))).scalars().all() if events else []
    by_event: dict[int, list[int]] = {}
    for ep in people:
        by_event.setdefault(ep.event_id, []).append(ep.entity_id)
    return [{**row(e), "people": by_event.get(e.id, [])} for e in events]


# ------------------------------------------------------ scheduled visits
@router.post("/jobs/{job_id}/visits", status_code=201)
def schedule_visit(job_id: int, body: VisitCreate, db: Session = Depends(get_db), user: User = Depends(writer)):
    """Rep required. Showroom defaults from the rep and can be changed."""
    job = get_job(db, job_id)
    rep = check_rep(db, body.rep_id or job.rep_id)
    _check_showroom(body.showroom)
    if body.starts_at.tzinfo is None:
        raise HTTPException(422, "The visit time must include a time zone.")
    v = ScheduledVisit(
        job_id=job.id,
        rep_id=rep.id,
        showroom=(body.showroom or rep.home_showroom) if body.kind == "showroom" else None,
        kind=body.kind,
        starts_at=body.starts_at,
        purpose=body.purpose,
        expected=body.expected,
        status="scheduled",
        created_by=user.id,
    )
    from ..services.absences import route

    v.rep_id, v.covering_for_id = route(db, rep.id)
    db.add(v)
    db.commit()
    return row(v)


@router.post("/visits/{visit_id}/resolve")
def resolve_visit(visit_id: int, body: VisitResolve, db: Session = Depends(get_db), user: User = Depends(writer)):
    """No-show or cancelled. A visit that happened is resolved by logging the event instead."""
    v = db.get(ScheduledVisit, visit_id)
    if v is None:
        raise HTTPException(404, "Visit not found.")
    if v.status != "scheduled":
        raise HTTPException(409, f"That visit is already {v.status.replace('_', ' ')}.")
    job = db.get(Job, v.job_id)
    v.status, v.resolved_at, v.resolved_by = body.status, now(), user.id
    ev = Event(
        job_id=job.id,
        kind="contact",
        summary=f"Visit {'no-show' if body.status == 'no_show' else 'cancelled'}: {body.note}",
        scheduled_visit_id=v.id,
        logged_by=user.id,
    )
    db.add(ev)
    db.flush()
    create_task(db, job, body.next_step, user, source_event_id=ev.id)
    db.commit()
    return row(v)


@router.post("/visits/{visit_id}/reschedule", status_code=201)
def reschedule_visit(visit_id: int, body: VisitReschedule, db: Session = Depends(get_db), user: User = Depends(writer)):
    """A rescheduled visit is still a scheduled visit — the old one points to the new one."""
    v = db.get(ScheduledVisit, visit_id)
    if v is None:
        raise HTTPException(404, "Visit not found.")
    if v.status != "scheduled":
        raise HTTPException(409, f"That visit is already {v.status.replace('_', ' ')}.")
    if body.starts_at.tzinfo is None:
        raise HTTPException(422, "The visit time must include a time zone.")
    new = ScheduledVisit(
        job_id=v.job_id,
        rep_id=v.rep_id,
        covering_for_id=v.covering_for_id,
        showroom=v.showroom,
        kind=v.kind,
        starts_at=body.starts_at,
        purpose=v.purpose,
        expected=v.expected,
        status="scheduled",
        created_by=user.id,
    )
    db.add(new)
    db.flush()
    v.status, v.resolved_at, v.resolved_by, v.rescheduled_to_id = "rescheduled", now(), user.id, new.id
    db.commit()
    return row(new)


@router.get("/visits")
def day_book(
    day: date | None = None,
    showroom: str | None = None,
    rep_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(member),
):
    """The rep's day, or the showroom's book — whoever's job it is."""
    start, end = day_bounds(day or today())
    stmt = select(ScheduledVisit, Job).join(Job, Job.id == ScheduledVisit.job_id).where(
        ScheduledVisit.starts_at >= start, ScheduledVisit.starts_at < end
    )
    if showroom:
        stmt = stmt.where(ScheduledVisit.showroom == showroom)
    if rep_id:
        stmt = stmt.where(ScheduledVisit.rep_id == rep_id)
    rows = db.execute(stmt.order_by(ScheduledVisit.starts_at)).all()
    reps = {u.id: u for u in db.scalars(select(User).where(User.id.in_(list({v.rep_id for v, _ in rows}))))} if rows else {}
    return [{**row(v), "job_name": j.name, "rep": user_out(reps.get(v.rep_id))} for v, j in rows]
