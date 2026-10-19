"""Jobs and who is on them."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Entity, Job, JobRole, User
from ..rules.constants import CLASSES, LEAD_SOURCES, PROJECT_TYPES, ROLE_CAPS, SHOWROOMS
from ..timeutil import now


def get_job(db: Session, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found.")
    return job


def check_fields(class_code=None, project_type=None, lead_source=None, lead_showroom=None) -> None:
    if class_code is not None and class_code not in CLASSES:
        raise HTTPException(422, f"Unknown class: {class_code}")
    if project_type is not None and project_type not in PROJECT_TYPES:
        raise HTTPException(422, f"Unknown project type: {project_type}")
    if lead_source is not None and lead_source not in LEAD_SOURCES:
        raise HTTPException(422, f"Unknown lead source: {lead_source}")
    if lead_showroom is not None and lead_showroom not in SHOWROOMS:
        raise HTTPException(422, f"Unknown showroom: {lead_showroom}")


def check_rep(db: Session, rep_id: int) -> User:
    rep = db.get(User, rep_id)
    if rep is None or not rep.active or rep.role == "pending":
        raise HTTPException(422, "The rep must be an active, set-up user.")
    return rep


def live_entity(db: Session, entity_id: int) -> Entity:
    ent = db.get(Entity, entity_id)
    if ent is None:
        raise HTTPException(422, "That person or company doesn't exist.")
    if ent.merged_into_id:
        ent = db.get(Entity, ent.merged_into_id)
    if ent is None or not ent.active:
        raise HTTPException(422, "That person or company is no longer active.")
    return ent


def add_role(db: Session, job: Job, entity_id: int, role: str, by: User) -> JobRole:
    """Puts someone on the job in a role. Where the role is capped, the
    oldest holder is deactivated — history keeps who held it and when."""
    if role not in ROLE_CAPS:
        raise HTTPException(422, f"Unknown role: {role}")
    ent = live_entity(db, entity_id)

    current = db.scalars(
        select(JobRole)
        .where(JobRole.job_id == job.id, JobRole.role == role, JobRole.active.is_(True))
        .order_by(JobRole.started_at, JobRole.id)
    ).all()
    for existing in current:
        if existing.entity_id == ent.id:
            return existing

    cap = ROLE_CAPS[role]
    if cap is not None and len(current) >= cap:
        for old in current[: len(current) - cap + 1]:
            old.active = False
            old.ended_at = now()

    jr = JobRole(job_id=job.id, entity_id=ent.id, role=role, active=True, created_by=by.id)
    db.add(jr)
    db.flush()
    if job.default_contact_id is None:
        job.default_contact_id = ent.id
    return jr
