from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth import member, writer
from ..db import get_db
from ..models import (
    Area,
    AuditLog,
    Candidate,
    CandidateTag,
    Entity,
    Event,
    EventPerson,
    Item,
    Job,
    JobRole,
    Sample,
    ScheduledVisit,
    Task,
    User,
)
from ..rules.constants import TASK_OPEN
from ..rules.normalize import norm_name
from ..schemas import JobCreate, JobHold, JobLose, JobRevive, JobUpdate, NextStep, PersonOnJob, RepChange
from ..serialize import entity_out, row, user_out
from ..services.jobs import add_role, check_fields, check_rep, get_job, live_entity
from ..services.progress import for_jobs as job_progress
from ..services.tasks import create_task
from ..timeutil import now, today

router = APIRouter(prefix="/jobs", tags=["jobs"])


# ------------------------------------------------------------- listing
def _summaries(db: Session, jobs: list[Job]) -> list[dict]:
    if not jobs:
        return []
    ids = [j.id for j in jobs]
    open_counts = dict(
        db.execute(
            select(Task.job_id, func.count()).where(Task.job_id.in_(ids), Task.status.in_(TASK_OPEN)).group_by(Task.job_id)
        ).all()
    )
    next_due = dict(
        db.execute(
            select(Task.job_id, func.min(Task.due_date))
            .where(Task.job_id.in_(ids), Task.status.in_(TASK_OPEN))
            .group_by(Task.job_id)
        ).all()
    )
    reps = {u.id: u for u in db.scalars(select(User).where(User.id.in_(list({j.rep_id for j in jobs}))))}
    contact_ids = {j.default_contact_id for j in jobs if j.default_contact_id}
    contacts = {e.id: e for e in db.scalars(select(Entity).where(Entity.id.in_(list(contact_ids))))} if contact_ids else {}
    progress = job_progress(db, ids)
    out = []
    for j in jobs:
        d = row(j)
        d["progress"] = progress.get(j.id)
        d["rep"] = user_out(reps.get(j.rep_id))
        d["default_contact"] = entity_out(contacts.get(j.default_contact_id)) if j.default_contact_id else None
        d["open_tasks"] = open_counts.get(j.id, 0)
        nd = next_due.get(j.id)
        d["next_due"] = nd.isoformat() if nd else None
        d["stuck"] = j.status == "active" and open_counts.get(j.id, 0) == 0
        out.append(d)
    return out


def _matches(text: str):
    """One search box: job name, address, or anyone on the job by name or phone."""
    like = f"%{text.lower()}%"
    person_conds = []
    n = norm_name(text)
    if n:
        person_conds.append(Entity.name_norm.contains(n))
    digits = "".join(c for c in text if c.isdigit())
    if len(digits) >= 4:
        person_conds.append(Entity.phone_norm.contains(digits))
    conds = [func.lower(Job.name).like(like), func.lower(Job.address).like(like)]
    if person_conds:
        people = select(JobRole.job_id).join(Entity, Entity.id == JobRole.entity_id).where(or_(*person_conds))
        conds.append(Job.id.in_(people))
    return or_(*conds)


@router.get("")
def list_jobs(
    mine: bool = False,
    status: str | None = None,
    q: str = "",
    limit: int = 100,
    db: Session = Depends(get_db),
    user: User = Depends(member),
):
    stmt = select(Job)
    if mine:
        stmt = stmt.where(Job.rep_id == user.id)
    if status:
        stmt = stmt.where(Job.status == status)
    text = q.strip()
    if text:
        stmt = stmt.where(_matches(text))
    stmt = stmt.order_by(Job.created_at.desc()).limit(max(1, min(limit, 300)))
    return _summaries(db, list(db.scalars(stmt)))


# -------------------------------------------------------------- create
@router.post("", status_code=201)
def create_job(body: JobCreate, db: Session = Depends(get_db), user: User = Depends(writer)):
    """Thin on purpose: a rep and one named person is enough to start."""
    rep = check_rep(db, body.rep_id or user.id)
    if rep.role != "rep" and body.rep_id is None and not user.is_admin:
        # Office staff creating a job must say whose it is.
        raise HTTPException(422, "Pick the rep this job belongs to.")
    class_code = body.class_code or rep.default_class
    if not class_code:
        raise HTTPException(422, "Pick the class (department) for this job.")
    check_fields(class_code, body.project_type, body.lead_source, body.lead_showroom)

    job = Job(
        name=body.name,
        address=body.address,
        class_code=class_code,
        project_type=body.project_type,
        lead_source=body.lead_source,
        lead_showroom=body.lead_showroom or (rep.home_showroom if body.lead_source == "walk_in" else None),
        rep_id=rep.id,
        status="active",
        created_by=user.id,
    )
    from ..services.absences import route

    job.rep_id, job.covering_for_id = route(db, rep.id)
    db.add(job)
    db.flush()
    for p in body.people:
        add_role(db, job, p.entity_id, p.role, user)

    event_id = None
    if body.first_event:
        ev = Event(
            job_id=job.id,
            kind=body.first_event.kind,
            channel=body.first_event.channel,
            direction=body.first_event.direction,
            summary=body.first_event.summary,
            showroom=user.home_showroom if body.first_event.kind == "showroom_visit" else None,
            logged_by=user.id,
        )
        db.add(ev)
        db.flush()
        for eid in {live_entity(db, p.entity_id).id for p in body.people}:
            db.add(EventPerson(event_id=ev.id, entity_id=eid))
        event_id = ev.id

    create_task(db, job, body.next_step, user, source_event_id=event_id)
    from ..services.templates import apply

    apply(db, job, "job_created", user)
    db.commit()
    return job_detail(db, job)


# ------------------------------------------------------------- detail
def job_detail(db: Session, job: Job) -> dict:
    roles = db.execute(
        select(JobRole, Entity).join(Entity, Entity.id == JobRole.entity_id).where(JobRole.job_id == job.id)
        .order_by(JobRole.active.desc(), JobRole.started_at)
    ).all()
    areas = list(db.scalars(select(Area).where(Area.job_id == job.id).order_by(Area.sort_order, Area.id)))
    candidates = list(db.scalars(select(Candidate).where(Candidate.job_id == job.id, Candidate.removed_at.is_(None)).order_by(Candidate.id)))
    tags = list(db.scalars(select(CandidateTag).where(CandidateTag.job_id == job.id).order_by(CandidateTag.id)))
    item_ids = {c.netsuite_item_id for c in candidates if c.netsuite_item_id}
    items = {i.netsuite_id: i for i in db.scalars(select(Item).where(Item.netsuite_id.in_(list(item_ids))))} if item_ids else {}
    samples = list(db.scalars(select(Sample).where(Sample.job_id == job.id).order_by(Sample.id)))
    tasks = list(
        db.scalars(
            select(Task).where(Task.job_id == job.id)
            .order_by(Task.status.in_(TASK_OPEN).desc(), Task.due_date, Task.id)
        )
    )
    visits = list(
        db.scalars(select(ScheduledVisit).where(ScheduledVisit.job_id == job.id).order_by(ScheduledVisit.starts_at.desc()))
    )
    rep = db.get(User, job.rep_id)

    tags_by_cand: dict[int, list[dict]] = {}
    for t in tags:
        tags_by_cand.setdefault(t.candidate_id, []).append(row(t))
    cand_out = []
    for c in candidates:
        d = row(c)
        item = items.get(c.netsuite_item_id) if c.netsuite_item_id else None
        d["item"] = row(item)
        # Our stock: NetSuite's name is the truth. Typed names only stand in until the item is known.
        if c.source == "stock" and item is not None:
            d["display_name"] = item.name
        else:
            d["display_name"] = c.name or f"Item #{c.netsuite_item_id} (details pending)"
        d["tags"] = tags_by_cand.get(c.id, [])
        d["needs_lead_time"] = c.source == "overseas" and c.lead_time_weeks is None
        cand_out.append(d)

    open_tasks = [t for t in tasks if t.status in TASK_OPEN]
    d = row(job)
    d.update(
        {
            "rep": user_out(rep),
            "owner_id": job.rep_id,
            "roles": [{**row(jr), "entity": entity_out(ent)} for jr, ent in roles],
            "areas": [row(a) for a in areas],
            "candidates": cand_out,
            "samples": [row(s) for s in samples],
            "tasks": [row(t) for t in tasks],
            "visits": [row(v) for v in visits],
            "open_tasks": len(open_tasks),
            "open_takeoff_id": next((t.id for t in open_tasks if t.kind == "takeoff"), None),
            "progress": job_progress(db, [job.id])[job.id],
            "stuck": job.status == "active" and not open_tasks,
        }
    )
    return d


@router.get("/{job_id}")
def get_job_detail(job_id: int, db: Session = Depends(get_db), _: User = Depends(member)):
    return job_detail(db, get_job(db, job_id))


@router.get("/{job_id}/timeline")
def timeline(job_id: int, everything: bool = False, db: Session = Depends(get_db), _: User = Depends(member)):
    """The job's story — or, with everything=1, every single field change."""
    get_job(db, job_id)
    stmt = select(AuditLog).where(AuditLog.job_id == job_id)
    if not everything:
        stmt = stmt.where(AuditLog.story.is_(True))
    entries = list(db.scalars(stmt.order_by(AuditLog.at.desc(), AuditLog.id.desc()).limit(500)))
    return [row(e) for e in entries]


# -------------------------------------------------------------- change
@router.patch("/{job_id}")
def update_job(job_id: int, body: JobUpdate, db: Session = Depends(get_db), _: User = Depends(writer)):
    job = get_job(db, job_id)
    data = body.model_dump(exclude_unset=True)
    if "name" in data and not data["name"]:
        raise HTTPException(422, "A job needs a name.")
    check_fields(data.get("class_code"), data.get("project_type"), data.get("lead_source"), data.get("lead_showroom"))
    if data.get("class_code") is None:
        data.pop("class_code", None)
    if data.get("default_contact_id") is not None:
        on_job = db.scalar(
            select(func.count()).select_from(JobRole).where(
                JobRole.job_id == job.id, JobRole.entity_id == data["default_contact_id"], JobRole.active.is_(True)
            )
        )
        if not on_job:
            raise HTTPException(422, "The default contact must be someone active on this job.")
    for k, v in data.items():
        setattr(job, k, v)
    db.commit()
    return job_detail(db, job)


@router.post("/{job_id}/rep")
def change_rep(job_id: int, body: RepChange, db: Session = Depends(get_db), _: User = Depends(writer)):
    """One rep per job. The new rep owns every open task from this moment."""
    job = get_job(db, job_id)
    check_rep(db, body.rep_id)
    from ..services.absences import route

    job.rep_id, job.covering_for_id = route(db, body.rep_id)
    db.commit()
    return job_detail(db, job)


@router.post("/{job_id}/roles", status_code=201)
def add_person(job_id: int, body: PersonOnJob, db: Session = Depends(get_db), user: User = Depends(writer)):
    job = get_job(db, job_id)
    add_role(db, job, body.entity_id, body.role, user)
    db.commit()
    return job_detail(db, job)


@router.delete("/{job_id}/roles/{role_id}")
def remove_person(job_id: int, role_id: int, db: Session = Depends(get_db), _: User = Depends(writer)):
    """Ends someone's role on the job. The record stays, with the end date."""
    job = get_job(db, job_id)
    jr = db.get(JobRole, role_id)
    if jr is None or jr.job_id != job.id or not jr.active:
        raise HTTPException(404, "Not an active role on this job.")
    active_people = db.scalar(
        select(func.count()).select_from(JobRole).where(JobRole.job_id == job.id, JobRole.active.is_(True))
    )
    if active_people <= 1:
        raise HTTPException(422, "A job needs at least one named person.")
    jr.active = False
    jr.ended_at = now()
    if job.default_contact_id == jr.entity_id:
        still_on = db.scalar(
            select(JobRole.entity_id).where(
                JobRole.job_id == job.id, JobRole.active.is_(True), JobRole.entity_id == jr.entity_id, JobRole.id != jr.id
            )
        )
        if not still_on:
            job.default_contact_id = db.scalar(
                select(JobRole.entity_id).where(JobRole.job_id == job.id, JobRole.active.is_(True), JobRole.id != jr.id)
                .order_by(JobRole.started_at)
            )
    db.commit()
    return job_detail(db, job)


# ------------------------------------------------------ hold, lose, revive
@router.post("/{job_id}/hold")
def hold_job(job_id: int, body: JobHold, db: Session = Depends(get_db), user: User = Depends(writer)):
    """Paused, not stuck. On the return date the rep gets a check-in task."""
    job = get_job(db, job_id)
    if job.status != "active":
        raise HTTPException(409, f"Only an active job can go on hold (this one is {job.status}).")
    if body.until <= today():
        raise HTTPException(422, "The return date must be in the future.")
    job.status, job.hold_until, job.hold_reason = "on_hold", body.until, body.reason
    create_task(
        db,
        job,
        NextStep(title=f"Check in — on hold: {body.reason}", assignee_id=job.rep_id, due_date=body.until, severity="notify"),
        user,
    )
    db.commit()
    return job_detail(db, job)


@router.post("/{job_id}/resume")
def resume_job(job_id: int, db: Session = Depends(get_db), _: User = Depends(writer)):
    job = get_job(db, job_id)
    if job.status != "on_hold":
        raise HTTPException(409, "This job isn't on hold.")
    job.status, job.hold_until, job.hold_reason = "active", None, None
    db.commit()
    return job_detail(db, job)


@router.post("/{job_id}/lose")
def lose_job(job_id: int, body: JobLose, db: Session = Depends(get_db), user: User = Depends(writer)):
    """Anyone can close a job as lost. Open steps are skipped, with the reason."""
    job = get_job(db, job_id)
    if job.status in ("lost", "closed"):
        raise HTTPException(409, f"This job is already {job.status}.")
    if body.reason == "other" and not body.note:
        raise HTTPException(422, "\"Other\" needs a note saying why.")
    job.status, job.lost_reason, job.lost_note = "lost", body.reason, body.note
    job.hold_until, job.hold_reason = None, None
    for t in db.scalars(select(Task).where(Task.job_id == job.id, Task.status.in_(TASK_OPEN))):
        t.status, t.outcome_note, t.completed_at, t.completed_by = "skipped", "Job lost", now(), user.id
    db.commit()
    return job_detail(db, job)


@router.post("/{job_id}/revive")
def revive_job(job_id: int, body: JobRevive, db: Session = Depends(get_db), user: User = Depends(writer)):
    """A lost job can come back — where it was, or with selection started over."""
    job = get_job(db, job_id)
    if job.status != "lost":
        raise HTTPException(409, "Only a lost job can be revived.")
    if body.mode == "fresh":
        for a in db.scalars(select(Area).where(Area.job_id == job.id, Area.status.in_(("open", "on_hold")))):
            a.status, a.hold_until, a.hold_reason = "dropped", None, None
    job.status, job.lost_reason, job.lost_note = "active", None, None
    create_task(db, job, body.next_step, user)
    db.commit()
    return job_detail(db, job)


# ------------------------------------------------------------- recent
@router.get("/{job_id}/people")
def job_people(job_id: int, db: Session = Depends(get_db), _: User = Depends(member)):
    rows = db.execute(
        select(JobRole, Entity).join(Entity, Entity.id == JobRole.entity_id)
        .where(JobRole.job_id == job_id, JobRole.active.is_(True))
    ).all()
    return [{"role": jr.role, "entity": entity_out(ent)} for jr, ent in rows]

