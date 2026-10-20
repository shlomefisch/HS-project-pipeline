"""Assembling an estimate from the job: chosen tiles, per area, priced from
NetSuite's Base Price. Footage on every chosen tile is a hard gate; everything else is a warning
the rep sees before anything goes to NetSuite."""

import logging
from collections.abc import Callable
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Area, Candidate, CandidateTag, Estimate, EstimateArea, EstimateLine, Item, Job, User
from .availability import GOOD, need_for, tile_unit

log = logging.getLogger("pipeline.estimates")


def _price_or_none(lookup: Callable[[int], Decimal | None] | None, item_id: int | None) -> Decimal | None:
    if lookup is None or item_id is None:
        return None
    try:
        return lookup(item_id)
    except Exception as exc:  # a missing price never stops the estimate; the rep types it
        log.warning("base price for %s unavailable: %s", item_id, exc)
        return None


def create(db: Session, job: Job, area_ids: list[int], note: str | None, by: User,
           price_lookup: Callable[[int], Decimal | None] | None) -> Estimate:
    if job.status != "active":
        raise HTTPException(409, "The job isn't active.")
    areas = [db.get(Area, a) for a in dict.fromkeys(area_ids)]
    if any(a is None or a.job_id != job.id for a in areas):
        raise HTTPException(422, "Those areas aren't all on this job.")
    ordered = [a.name for a in areas if a.status in ("ordered", "delivered")]
    if ordered:
        raise HTTPException(422, f"{', '.join(ordered)} is already on an order. A change there is a change to that order; new work is a new area.")
    held = [a.name for a in areas if a.status in ("on_hold", "dropped")]
    if held:
        raise HTTPException(422, f"{', '.join(held)} is on hold or dropped — it becomes its own order later.")
    tags = list(db.scalars(
        select(CandidateTag).where(CandidateTag.area_id.in_([a.id for a in areas]), CandidateTag.status == "chosen")
        .order_by(CandidateTag.area_id, CandidateTag.id)
    ))
    by_area = {a.id: a for a in areas}
    empty = [a.name for a in areas if not any(t.area_id == a.id for t in tags)]
    if empty:
        raise HTTPException(422, "Choose a tile first for: " + ", ".join(empty) + ".")
    no_number = [f"{_tile_name(db, t)} ({by_area[t.area_id].name})" for t in tags if t.quantity is None]
    if no_number:
        raise HTTPException(422, "No footage, no estimate. Still missing on: " + ", ".join(no_number) + ".")

    est = Estimate(job_id=job.id, status="draft", note=note, created_by=by.id)
    db.add(est)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This job already has an estimate being put together. Finish or discard it first.") from exc
    for a in areas:
        db.add(EstimateArea(estimate_id=est.id, area_id=a.id, job_id=job.id))

    order = [a.id for a in areas]
    for i, t in enumerate(sorted(tags, key=lambda t: (order.index(t.area_id), t.id))):
        cand = db.get(Candidate, t.candidate_id)
        area = by_area[t.area_id]
        item = db.get(Item, cand.netsuite_item_id) if cand.netsuite_item_id else None
        name = cand.name or (item.name if item else f"Item #{cand.netsuite_item_id}")
        unit = tile_unit(db, cand)
        qty = t.quantity  # the number on the tile, square feet or pieces
        base = _price_or_none(price_lookup, cand.netsuite_item_id) if cand.source == "stock" else None
        db.add(EstimateLine(
            estimate_id=est.id, job_id=job.id, tag_id=t.id, area_id=area.id, netsuite_item_id=cand.netsuite_item_id,
            description=f"{name} — {area.name}", quantity=qty, unit=unit, base_price=base, price=base, sort_order=i,
        ))
    db.flush()
    from .templates import apply

    apply(db, job, "estimate_started", by)
    return est


def _tile_name(db: Session, tag: CandidateTag) -> str:
    cand = db.get(Candidate, tag.candidate_id)
    item = db.get(Item, cand.netsuite_item_id) if cand.netsuite_item_id else None
    return cand.name or (item.name if item else f"Item #{cand.netsuite_item_id}")


def warnings(db: Session, est: Estimate, lines: list[EstimateLine]) -> list[str]:
    """What the rep should know before this goes to NetSuite."""
    out = []
    for ln in lines:
        tag = db.get(CandidateTag, ln.tag_id) if ln.tag_id else None
        if tag and tag.avail_status not in GOOD:
            state = {"two_lots": "two lots only", "short": "short", None: "not checked"}.get(tag.avail_status, tag.avail_status)
            out.append(f"{ln.description}: availability {state}.")
        elif tag and tag.avail_status == "available" and tag.avail_need is not None:
            need = need_for(tag)
            if need is not None and Decimal(need) != Decimal(tag.avail_need):
                out.append(f"{ln.description}: availability was checked for {float(tag.avail_need):,.0f}, it now needs {float(need):,.0f} — check again.")
        if ln.quantity is None:
            out.append(f"{ln.description}: no quantity — counted in {ln.unit}, enter it.")
        if ln.price is None:
            out.append(f"{ln.description}: no price — NetSuite has no Base Price for it, enter one.")
    return out
