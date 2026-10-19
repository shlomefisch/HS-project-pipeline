"""Product selection: areas as tags, one flat list of tiles, a decision per area."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import member, writer
from ..db import get_db
from ..models import Area, Candidate, CandidateTag, Item, Sample, User
from ..rules.qr import parse_item_code
from ..schemas import (
    AreaCreate,
    AreaUpdate,
    CandidateCreate,
    CandidateUpdate,
    SampleCreate,
    SampleUpdate,
    TagCreate,
    TagUpdate,
)
from ..serialize import row
from ..services.jobs import get_job
from ..timeutil import now, today

router = APIRouter(tags=["selection"])


def _area_on_job(db: Session, area_id: int, job_id: int) -> Area:
    area = db.get(Area, area_id)
    if area is None or area.job_id != job_id:
        raise HTTPException(422, "That area isn't on this job.")
    return area


# --------------------------------------------------------------- areas
@router.post("/jobs/{job_id}/areas", status_code=201)
def create_area(job_id: int, body: AreaCreate, db: Session = Depends(get_db), user: User = Depends(writer)):
    job = get_job(db, job_id)
    exists = db.scalar(select(Area).where(Area.job_id == job.id, func.lower(Area.name) == body.name.lower()))
    if exists:
        return row(exists)
    order = (db.scalar(select(func.max(Area.sort_order)).where(Area.job_id == job.id)) or 0) + 1
    area = Area(job_id=job.id, name=body.name, status="open", sort_order=order, created_by=user.id)
    db.add(area)
    db.commit()
    return row(area)


@router.patch("/areas/{area_id}")
def update_area(area_id: int, body: AreaUpdate, db: Session = Depends(get_db), _: User = Depends(writer)):
    area = db.get(Area, area_id)
    if area is None:
        raise HTTPException(404, "Area not found.")
    data = body.model_dump(exclude_unset=True)
    status = data.get("status")
    if status == "on_hold":
        until, reason = data.get("hold_until") or area.hold_until, data.get("hold_reason") or area.hold_reason
        if not until or not reason:
            raise HTTPException(422, "On hold needs a date to come back and a reason.")
        if until <= today():
            raise HTTPException(422, "The return date must be in the future.")
        data["hold_until"], data["hold_reason"] = until, reason
    elif status is not None:
        data["hold_until"], data["hold_reason"] = None, None
    if status == "decided":
        chosen = db.scalar(
            select(func.count()).select_from(CandidateTag).where(
                CandidateTag.area_id == area.id, CandidateTag.status == "chosen"
            )
        )
        if not chosen:
            raise HTTPException(422, f"Choose at least one tile for {area.name} before marking it decided.")
    for k, v in data.items():
        setattr(area, k, v)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "There's already an area with that name on this job.") from exc
    return row(area)


# ---------------------------------------------------------- candidates
@router.post("/jobs/{job_id}/candidates", status_code=201)
def create_candidate(job_id: int, body: CandidateCreate, db: Session = Depends(get_db), user: User = Depends(writer)):
    job = get_job(db, job_id)
    name = body.name
    if body.source == "stock":
        if body.netsuite_item_id is None:
            raise HTTPException(422, "A stock tile needs its item — scan the tag or pick it from the list.")
        item = db.get(Item, body.netsuite_item_id)
        # Not in the local list yet (e.g. sync behind): still create it; the name fills in later.
        if item is not None and not name:
            name = item.name
    elif not name:
        raise HTTPException(422, "Give the tile a name — local and overseas tiles have no tag to scan.")

    cand = Candidate(
        job_id=job.id,
        source=body.source,
        netsuite_item_id=body.netsuite_item_id,
        name=name,
        supplier=body.supplier,
        lead_time_weeks=body.lead_time_weeks,
        notes=body.notes,
        created_by=user.id,
    )
    db.add(cand)
    db.flush()
    for area_id in dict.fromkeys(body.area_ids):
        _area_on_job(db, area_id, job.id)
        db.add(CandidateTag(job_id=job.id, candidate_id=cand.id, area_id=area_id, status="considering"))
    db.commit()
    return row(cand)


@router.patch("/candidates/{candidate_id}")
def update_candidate(candidate_id: int, body: CandidateUpdate, db: Session = Depends(get_db), _: User = Depends(writer)):
    cand = db.get(Candidate, candidate_id)
    if cand is None:
        raise HTTPException(404, "Tile not found.")
    data = body.model_dump(exclude_unset=True)
    if "name" in data and not data["name"] and cand.netsuite_item_id is None:
        raise HTTPException(422, "A tile needs a name.")
    for k, v in data.items():
        setattr(cand, k, v)
    db.commit()
    return row(cand)


# ---------------------------------------------------------------- tags
@router.post("/candidates/{candidate_id}/tags", status_code=201)
def add_tag(candidate_id: int, body: TagCreate, db: Session = Depends(get_db), _: User = Depends(writer)):
    """Consider the same tile for another area. One tile, one more line."""
    cand = db.get(Candidate, candidate_id)
    if cand is None:
        raise HTTPException(404, "Tile not found.")
    _area_on_job(db, body.area_id, cand.job_id)
    existing = db.scalar(select(CandidateTag).where(CandidateTag.candidate_id == cand.id, CandidateTag.area_id == body.area_id))
    if existing:
        return row(existing)
    tag = CandidateTag(job_id=cand.job_id, candidate_id=cand.id, area_id=body.area_id, quantity=body.quantity)
    db.add(tag)
    db.commit()
    return row(tag)


@router.patch("/tags/{tag_id}")
def update_tag(tag_id: int, body: TagUpdate, db: Session = Depends(get_db), user: User = Depends(writer)):
    """The decision — per area. Declined stays on the list, crossed out, with its reason."""
    tag = db.get(CandidateTag, tag_id)
    if tag is None:
        raise HTTPException(404, "Not found.")
    data = body.model_dump(exclude_unset=True)
    if "quantity" in data:
        tag.quantity = data["quantity"]
    status = data.get("status")
    if status == "declined":
        reason = data.get("reason")
        if not reason:
            raise HTTPException(422, "Why was it declined? A reason is required.")
        tag.status, tag.reason, tag.decided_at, tag.decided_by = "declined", reason, now(), user.id
    elif status == "chosen":
        tag.status, tag.reason, tag.decided_at, tag.decided_by = "chosen", data.get("reason"), now(), user.id
    elif status == "considering":
        # Un-crossing: the decision is undone; the old one stays in the history.
        tag.status, tag.reason, tag.decided_at, tag.decided_by = "considering", None, None, None
    db.commit()
    return row(tag)


@router.delete("/tags/{tag_id}")
def remove_tag(tag_id: int, db: Session = Depends(get_db), _: User = Depends(writer)):
    """For mis-taps only. Once a decision is made, it is crossed out, never removed."""
    tag = db.get(CandidateTag, tag_id)
    if tag is None:
        raise HTTPException(404, "Not found.")
    if tag.status != "considering":
        raise HTTPException(409, "A decided tile can't be removed — decline it instead, so the history stays.")
    db.delete(tag)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------- samples
@router.post("/jobs/{job_id}/samples", status_code=201)
def create_sample(job_id: int, body: SampleCreate, db: Session = Depends(get_db), user: User = Depends(writer)):
    job = get_job(db, job_id)
    if body.area_id is not None:
        _area_on_job(db, body.area_id, job.id)
    if body.candidate_id is not None:
        cand = db.get(Candidate, body.candidate_id)
        if cand is None or cand.job_id != job.id:
            raise HTTPException(422, "That tile isn't on this job.")
    s = Sample(job_id=job.id, created_by=user.id, status="requested", **body.model_dump())
    db.add(s)
    db.commit()
    return row(s)


@router.patch("/samples/{sample_id}")
def update_sample(sample_id: int, body: SampleUpdate, db: Session = Depends(get_db), _: User = Depends(writer)):
    s = db.get(Sample, sample_id)
    if s is None:
        raise HTTPException(404, "Sample not found.")
    data = body.model_dump(exclude_unset=True)
    if data.get("status") == "sent" and not data.get("sent_on") and not s.sent_on:
        data["sent_on"] = today()
    for k, v in data.items():
        setattr(s, k, v)
    db.commit()
    return row(s)


# --------------------------------------------------------------- items
@router.get("/items/resolve")
def resolve_item(code: str, db: Session = Depends(get_db), _: User = Depends(member)):
    """A scanned QR tag -> the item. Unknown ids still come back, so the scan is never lost."""
    item_id = parse_item_code(code)
    if item_id is None:
        raise HTTPException(422, "That code doesn't contain an item number.")
    item = db.get(Item, item_id)
    return {"netsuite_id": item_id, "found": item is not None, "item": row(item)}


@router.get("/items")
def search_items(q: str = "", limit: int = 25, db: Session = Depends(get_db), _: User = Depends(member)):
    stmt = select(Item).where(Item.active.is_(True))
    text = q.strip().lower()
    if text:
        like = f"%{text}%"
        stmt = stmt.where(func.lower(Item.name).like(like) | func.lower(func.coalesce(Item.sku, "")).like(like))
    return [row(i) for i in db.scalars(stmt.order_by(Item.name).limit(min(limit, 100)))]
