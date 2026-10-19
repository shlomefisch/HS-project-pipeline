"""People and companies: duplicate matching and merging."""

from fastapi import HTTPException
from sqlalchemy import Float, func, literal, or_, select, update
from sqlalchemy.orm import Session

from ..models import Entity, EventPerson, Job, JobRole
from ..rules.normalize import norm_email, norm_name, norm_phone

# Tuned on real cases: "Pinchas Kish" vs "Pinches Kisch" scores 0.42,
# unrelated names score under 0.2. Word similarity catches a short entry
# like "AtoZ" against "AtoZ Construction".
NAME_SIMILARITY = 0.35
WORD_SIMILARITY = 0.9
WORD_MIN_LEN = 4
MAX_MATCHES = 8


def apply_norms(entity: Entity) -> None:
    entity.name_norm = norm_name(entity.name)
    entity.phone_norm = norm_phone(entity.phone)
    entity.email_norm = norm_email(entity.email)


def find_matches(
    db: Session,
    name: str | None,
    phone: str | None,
    email: str | None,
    exclude_id: int | None = None,
) -> list[dict]:
    """Possible duplicates: same phone, same email, or a close name.

    Close matches are returned, not only exact ones — "Rifky Design" should
    surface "Rifky Designs".
    """
    n, p, e = norm_name(name), norm_phone(phone), norm_email(email)
    if not (n or p or e):
        return []

    conditions = []
    if p:
        conditions.append(Entity.phone_norm == p)
    if e:
        conditions.append(Entity.email_norm == e)
    if n:
        conditions.append(Entity.name_norm == n)
        conditions.append(func.similarity(Entity.name_norm, n) >= NAME_SIMILARITY)
        if len(n) >= WORD_MIN_LEN:
            conditions.append(func.word_similarity(n, Entity.name_norm) >= WORD_SIMILARITY)

    if n:
        sim = func.greatest(
            func.similarity(Entity.name_norm, n),
            func.word_similarity(n, Entity.name_norm) if len(n) >= WORD_MIN_LEN else literal(0.0, Float),
        )
    else:
        sim = literal(0.0, Float)
    stmt = (
        select(Entity, sim.label("sim"))
        .where(Entity.active.is_(True), Entity.merged_into_id.is_(None), or_(*conditions))
        .order_by(sim.desc())
        .limit(MAX_MATCHES * 3)
    )
    if exclude_id:
        stmt = stmt.where(Entity.id != exclude_id)

    matches = []
    for ent, score in db.execute(stmt).all():
        reasons = []
        if p and ent.phone_norm == p:
            reasons.append("same phone")
        if e and ent.email_norm == e:
            reasons.append("same email")
        if n and ent.name_norm == n:
            reasons.append("same name")
        elif n and score is not None and float(score) >= NAME_SIMILARITY:
            reasons.append("similar name")
        if reasons:
            strength = 2 if ("same phone" in reasons or "same email" in reasons) else 1
            matches.append({"entity": ent, "reasons": reasons, "strength": strength, "score": float(score or 0)})
    matches.sort(key=lambda m: (-m["strength"], -m["score"]))
    return matches[:MAX_MATCHES]


def merge(db: Session, source: Entity, target: Entity) -> None:
    """Folds a duplicate into the real record. The duplicate stays, marked merged — nothing is deleted."""
    if source.id == target.id:
        raise HTTPException(400, "Can't merge a record into itself.")
    if target.merged_into_id:
        raise HTTPException(400, "The target was itself merged into another record — merge into that one.")

    for role in db.scalars(select(JobRole).where(JobRole.entity_id == source.id)):
        role.entity_id = target.id
    for job in db.scalars(select(Job).where(Job.default_contact_id == source.id)):
        job.default_contact_id = target.id
    for child in db.scalars(select(Entity).where(Entity.company_id == source.id)):
        child.company_id = target.id

    # Event attendance: move, skipping events where the target is already listed.
    already = set(db.scalars(select(EventPerson.event_id).where(EventPerson.entity_id == target.id)))
    for ep in db.scalars(select(EventPerson).where(EventPerson.entity_id == source.id)).all():
        if ep.event_id in already:
            db.delete(ep)
        else:
            db.execute(
                update(EventPerson)
                .where(EventPerson.event_id == ep.event_id, EventPerson.entity_id == source.id)
                .values(entity_id=target.id)
            )

    # Fill gaps on the target from the duplicate.
    for field in ("phone", "email", "address", "netsuite_customer_id"):
        if not getattr(target, field) and getattr(source, field):
            setattr(target, field, getattr(source, field))
    apply_norms(target)

    source.merged_into_id = target.id
    source.active = False
