from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth import admin, member, writer
from ..db import get_db
from ..models import Entity, Job, JobRole, User
from ..rules.normalize import norm_name, norm_phone
from ..schemas import EntityCheck, EntityCreate, EntityUpdate
from ..serialize import entity_out, row
from ..services.people import apply_norms, find_matches, merge

router = APIRouter(prefix="/entities", tags=["people"])


def _match_out(m: dict) -> dict:
    return {"entity": entity_out(m["entity"]), "reasons": m["reasons"]}


@router.get("")
def search_entities(q: str = "", limit: int = 30, db: Session = Depends(get_db), _: User = Depends(member)):
    stmt = select(Entity).where(Entity.active.is_(True), Entity.merged_into_id.is_(None))
    n = norm_name(q)
    p = norm_phone(q)
    if q.strip():
        conds = [Entity.name_norm.contains(n)] if n else []
        if n:
            conds.append(func.similarity(Entity.name_norm, n) >= 0.3)
        if p:
            conds.append(Entity.phone_norm.contains(p))
        if "@" in q:
            conds.append(Entity.email_norm.contains(q.strip().lower()))
        if not conds:
            return []
        stmt = stmt.where(or_(*conds))
        if n:
            stmt = stmt.order_by(func.similarity(Entity.name_norm, n).desc())
    else:
        stmt = stmt.order_by(Entity.created_at.desc())
    return [entity_out(e) for e in db.scalars(stmt.limit(min(limit, 100)))]


@router.post("/check")
def check_duplicates(body: EntityCheck, db: Session = Depends(get_db), _: User = Depends(member)):
    return {"matches": [_match_out(m) for m in find_matches(db, body.name, body.phone, body.email)]}


@router.post("", status_code=201)
def create_entity(body: EntityCreate, db: Session = Depends(get_db), user: User = Depends(writer)):
    matches = find_matches(db, body.name, body.phone, body.email)
    if matches and not body.confirm_new:
        # The app shows these and only allows "create new" once they are declined.
        raise HTTPException(409, {"message": "Possible duplicates found.", "matches": [_match_out(m) for m in matches]})
    if body.company_id is not None and db.get(Entity, body.company_id) is None:
        raise HTTPException(422, "That company doesn't exist.")
    ent = Entity(**body.model_dump(exclude={"confirm_new"}), created_by=user.id, active=True)
    apply_norms(ent)
    db.add(ent)
    db.commit()
    return entity_out(ent)


@router.get("/{entity_id}")
def get_entity(entity_id: int, db: Session = Depends(get_db), _: User = Depends(member)):
    """One record, and every job it is on — the 'all of Rifky's jobs' view."""
    ent = db.get(Entity, entity_id)
    if ent is None:
        raise HTTPException(404, "Not found.")
    rows = db.execute(
        select(JobRole, Job)
        .join(Job, Job.id == JobRole.job_id)
        .where(JobRole.entity_id == ent.id)
        .order_by(JobRole.active.desc(), Job.created_at.desc())
    ).all()
    jobs = [
        {
            "job_id": job.id,
            "job_name": job.name,
            "job_status": job.status,
            "class_code": job.class_code,
            "role": jr.role,
            "role_active": jr.active,
            "started_at": jr.started_at.isoformat() if jr.started_at else None,
            "ended_at": jr.ended_at.isoformat() if jr.ended_at else None,
        }
        for jr, job in rows
    ]
    company = entity_out(db.get(Entity, ent.company_id)) if ent.company_id else None
    contacts = [entity_out(c) for c in db.scalars(select(Entity).where(Entity.company_id == ent.id, Entity.active.is_(True)))]
    merged_into = entity_out(db.get(Entity, ent.merged_into_id)) if ent.merged_into_id else None
    return {"entity": entity_out(ent), "jobs": jobs, "company": company, "contacts": contacts, "merged_into": merged_into}


@router.patch("/{entity_id}")
def update_entity(entity_id: int, body: EntityUpdate, db: Session = Depends(get_db), _: User = Depends(writer)):
    ent = db.get(Entity, entity_id)
    if ent is None or not ent.active:
        raise HTTPException(404, "Not found.")
    data = body.model_dump(exclude_unset=True)
    if "name" in data and not data["name"]:
        raise HTTPException(422, "A name is required.")
    for k, v in data.items():
        setattr(ent, k, v)
    apply_norms(ent)
    db.commit()
    return entity_out(ent)


@router.post("/{entity_id}/merge-into/{target_id}")
def merge_entities(entity_id: int, target_id: int, db: Session = Depends(get_db), _: User = Depends(admin)):
    source, target = db.get(Entity, entity_id), db.get(Entity, target_id)
    if source is None or target is None:
        raise HTTPException(404, "Not found.")
    merge(db, source, target)
    db.commit()
    return {"merged": row(source, skip=("name_norm", "phone_norm", "email_norm")), "into": entity_out(target)}
