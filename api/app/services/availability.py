"""Availability, per tile per area.

Our stock: available means enough free (uncommitted) in ONE lot. Enough only
across lots counts as short, until the rep decides to go ahead on two lots.
Local supply: someone calls the supplier. Overseas: someone confirms the lead time.
Whenever the answer is short, the rep gets a task to tell the customer.
"""

import re
from collections.abc import Callable
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Area, Candidate, CandidateTag, Item, Job, Task, User
from ..rules.constants import TASK_OPEN
from ..schemas import NextStep
from ..timeutil import now, today
from .tasks import create_task

GOOD = ("available", "override", "confirmed")
SQFT = re.compile(r"^(sf|sq\.? ?ft\.?|sqft|square f)", re.I)


def _fmt(n) -> str:
    v = float(n)
    return f"{v:,.0f}" if v == int(v) else f"{v:,.2f}"


def _parts(db: Session, tag: CandidateTag) -> tuple[Job, Area, Candidate, str]:
    job = db.get(Job, tag.job_id)
    area = db.get(Area, tag.area_id)
    cand = db.get(Candidate, tag.candidate_id)
    item = db.get(Item, cand.netsuite_item_id) if cand.netsuite_item_id else None
    name = cand.name or (item.name if item else f"Item #{cand.netsuite_item_id}")
    return job, area, cand, name


def need_for(tag: CandidateTag, area: Area | None = None) -> Decimal | None:
    """What this tile has to cover in this area. The number on the tile is the boss;
    the area's number only ever fills in an empty tile when it's chosen."""
    return tag.quantity


def tile_unit(db: Session, cand: Candidate) -> str:
    """How the tile is counted: the item's NetSuite unit for our stock, square feet otherwise."""
    item = db.get(Item, cand.netsuite_item_id) if cand.source == "stock" and cand.netsuite_item_id else None
    return item.unit if item is not None and item.unit else "SF"


def in_square_feet(unit: str | None) -> bool:
    return bool(SQFT.match((unit or "SF").strip()))


def fill_from_area(db: Session, tag: CandidateTag) -> None:
    """A chosen tile with no number of its own starts from the area's number.
    Never over a number someone typed, and never for tiles counted by the piece."""
    if tag.status != "chosen" or tag.quantity is not None:
        return
    area = db.get(Area, tag.area_id)
    cand = db.get(Candidate, tag.candidate_id)
    if area is None or cand is None or area.footage is None:
        return
    if in_square_feet(tile_unit(db, cand)):
        tag.quantity = area.footage


def _tell_rep(db: Session, job: Job, area: Area, tile: str, why: str, by: User) -> None:
    title = f"Short: {tile} for {area.name} — tell the customer"
    exists = db.scalar(select(Task.id).where(Task.job_id == job.id, Task.title == title, Task.status.in_(TASK_OPEN)))
    if exists:
        return
    create_task(
        db, job,
        NextStep(title=title, assignee_id=job.rep_id, due_date=today(), severity="notify", area_id=area.id, notes=why),
        by,
    )


def _record(tag: CandidateTag, by: User, status: str, summary: str, *, lot=None, free=None, need=None, note=None) -> None:
    tag.avail_status, tag.avail_summary = status, summary
    tag.avail_lot, tag.avail_free, tag.avail_need, tag.avail_note = lot, free, need, note
    tag.avail_checked_at, tag.avail_checked_by = now(), by.id


def check_stock(db: Session, tag: CandidateTag, by: User, fetch_stock: Callable[[int], dict]) -> CandidateTag:
    job, area, cand, tile = _parts(db, tag)
    if tag.status == "declined":
        raise HTTPException(409, "This tile was declined for the area.")
    if cand.source != "stock" or cand.netsuite_item_id is None:
        raise HTTPException(422, "Only our own stock can be checked here — confirm local or overseas tiles instead.")
    need = need_for(tag, area)
    if not need:
        raise HTTPException(422, f"{tile} for {area.name} has no footage yet. Enter it on the tile first.")
    item = db.get(Item, cand.netsuite_item_id)
    if item is not None and item.unit and not SQFT.match(item.unit.strip()):
        raise HTTPException(
            422,
            f"NetSuite counts this item in {item.unit}, not square feet, so it can't be compared with the footage. "
            "Check it by hand on the stock box.",
        )
    stock = fetch_stock(cand.netsuite_item_id)
    rows = stock.get("rows", [])
    total = Decimal(str(stock.get("totals", {}).get("available", 0)))
    if stock.get("by_lot"):
        best = max(rows, key=lambda r: r["available"], default=None)
        best_free = Decimal(str(best["available"])) if best else Decimal(0)
        best_lot = best.get("lot") if best else None
    else:  # not lot-tracked: it's all one lot
        best_free, best_lot = total, None

    head = f"{tile} for {area.name}"
    if best_free >= need:
        lot_txt = f" in lot {best_lot}" if best_lot else ""
        _record(tag, by, "available", f"Available: {head}{lot_txt} — {_fmt(best_free)} free, needs {_fmt(need)}",
                lot=best_lot, free=best_free, need=need)
    elif total >= need:
        _record(tag, by, "two_lots",
                f"Two lots only: {head} — biggest lot {best_lot} has {_fmt(best_free)}, needs {_fmt(need)} ({_fmt(total)} free in all)",
                lot=best_lot, free=total, need=need)
        _tell_rep(db, job, area, tile, f"No single lot covers {_fmt(need)} sf. Biggest lot {best_lot}: {_fmt(best_free)}. "
                  "Either go ahead on two lots (your call, on the Plans tab) or offer something else.", by)
    else:
        _record(tag, by, "short", f"Short: {head} — {_fmt(total)} free, needs {_fmt(need)}",
                lot=best_lot, free=total, need=need)
        _tell_rep(db, job, area, tile, f"Only {_fmt(total)} sf free, needs {_fmt(need)}.", by)
    return tag


def override_two_lots(db: Session, tag: CandidateTag, by: User, reason: str) -> CandidateTag:
    job, area, _, tile = _parts(db, tag)
    if not (by.id == job.rep_id or by.is_admin or by.role == "management"):
        raise HTTPException(403, "Going ahead on two lots is the rep's call.")
    if tag.avail_status != "two_lots":
        raise HTTPException(409, "Only a tile that's short on one lot (but enough on two) can go ahead on two lots.")
    if not reason:
        raise HTTPException(422, "Say why it's fine on two lots.")
    tag.avail_status, tag.avail_note = "override", reason
    tag.avail_summary = f"Going ahead on two lots: {tile} for {area.name} — {reason}"
    tag.avail_checked_at, tag.avail_checked_by = now(), by.id
    return tag


def confirm_outside(db: Session, tag: CandidateTag, by: User, ok: bool, note: str | None, lead_time_weeks: int | None) -> CandidateTag:
    job, area, cand, tile = _parts(db, tag)
    if cand.source == "stock":
        raise HTTPException(422, "Our own stock is checked against NetSuite — use Check.")
    if cand.source == "overseas" and ok and lead_time_weeks is None and cand.lead_time_weeks is None:
        raise HTTPException(422, "Give the confirmed lead time in weeks.")
    if not ok and not note:
        raise HTTPException(422, "Say what the supplier said.")
    if lead_time_weeks is not None:
        cand.lead_time_weeks = lead_time_weeks
    head = f"{tile} for {area.name}"
    if ok:
        what = f"lead time {cand.lead_time_weeks} weeks" if cand.source == "overseas" else "supplier has it"
        _record(tag, by, "confirmed", f"Confirmed: {head} — {what}" + (f" ({note})" if note else ""), note=note)
    else:
        _record(tag, by, "short", f"Short: {head} — {note}", note=note)
        _tell_rep(db, job, area, tile, note, by)
    return tag
