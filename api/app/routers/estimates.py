"""Estimates on a job: assembled here, priced from NetSuite's Base Price,
changed by the rep wherever he wants. Nothing is sent to NetSuite yet."""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import member, writer
from ..config import settings
from ..db import get_db
from ..models import Estimate, EstimateArea, EstimateLine, User
from ..schemas import EstimateCreate, EstimateLineUpdate
from ..serialize import row
from ..services import estimates as E
from ..services.jobs import get_job

router = APIRouter(tags=["estimates"])


def _base_price(item_id: int) -> Decimal | None:
    """Live from NetSuite; None when NetSuite isn't connected or has no price."""
    if not settings.netsuite_configured:
        return None
    from ..services import pricing
    from ..services.item_sync import client_from_settings

    return pricing.base_price(client_from_settings, item_id)


def estimate_out(db: Session, est: Estimate) -> dict:
    lines = list(db.scalars(select(EstimateLine).where(EstimateLine.estimate_id == est.id).order_by(EstimateLine.sort_order, EstimateLine.id)))
    d = row(est)
    d["area_ids"] = list(db.scalars(select(EstimateArea.area_id).where(EstimateArea.estimate_id == est.id)))
    out_lines = []
    total = Decimal(0)
    for ln in lines:
        x = row(ln)
        x["overridden"] = ln.price is not None and ln.base_price is not None and ln.price != ln.base_price
        amount = (ln.price * ln.quantity) if ln.price is not None and ln.quantity is not None else None
        x["amount"] = float(round(amount, 2)) if amount is not None else None
        total += amount or 0
        out_lines.append(x)
    d["lines"] = out_lines
    d["total"] = float(round(total, 2))
    d["warnings"] = E.warnings(db, est, lines)
    return d


def _est(db: Session, estimate_id: int) -> Estimate:
    est = db.get(Estimate, estimate_id)
    if est is None:
        raise HTTPException(404, "Estimate not found.")
    return est


def _draft(db: Session, estimate_id: int) -> Estimate:
    est = _est(db, estimate_id)
    if est.status != "draft":
        raise HTTPException(409, "This estimate is no longer being put together.")
    return est


@router.get("/jobs/{job_id}/estimates")
def list_estimates(job_id: int, db: Session = Depends(get_db), _: User = Depends(member)):
    get_job(db, job_id)
    ests = db.scalars(select(Estimate).where(Estimate.job_id == job_id, Estimate.status != "discarded").order_by(Estimate.id.desc()))
    return [estimate_out(db, e) for e in ests]


@router.post("/jobs/{job_id}/estimates", status_code=201)
def create_estimate(job_id: int, body: EstimateCreate, db: Session = Depends(get_db), user: User = Depends(writer)):
    job = get_job(db, job_id)
    est = E.create(db, job, body.area_ids, body.note, user, _base_price)
    db.commit()
    return estimate_out(db, est)


@router.patch("/estimate-lines/{line_id}")
def update_line(line_id: int, body: EstimateLineUpdate, db: Session = Depends(get_db), _: User = Depends(writer)):
    ln = db.get(EstimateLine, line_id)
    if ln is None:
        raise HTTPException(404, "Line not found.")
    est = _draft(db, ln.estimate_id)
    data = body.model_dump(exclude_unset=True)
    if "quantity" in data and data["quantity"] is None:
        raise HTTPException(422, "A line needs a quantity.")
    if "price" in data and data["price"] is None:
        data["price"] = ln.base_price  # clearing a changed price goes back to Base Price
    for k, v in data.items():
        setattr(ln, k, v)
    db.commit()
    return estimate_out(db, est)


@router.post("/estimates/{estimate_id}/refresh-prices")
def refresh_prices(estimate_id: int, db: Session = Depends(get_db), _: User = Depends(writer)):
    """Re-read Base Price from NetSuite. Prices the rep changed stay as he set them."""
    est = _draft(db, estimate_id)
    from ..services import pricing

    pricing._cache.clear()
    for ln in db.scalars(select(EstimateLine).where(EstimateLine.estimate_id == est.id)):
        if ln.netsuite_item_id is None:
            continue
        changed = ln.price is not None and ln.base_price is not None and ln.price != ln.base_price
        new = E._price_or_none(_base_price, ln.netsuite_item_id)
        ln.base_price = new
        if not changed or ln.price is None:
            ln.price = new
    db.commit()
    return estimate_out(db, est)


@router.post("/estimates/{estimate_id}/discard")
def discard_estimate(estimate_id: int, db: Session = Depends(get_db), _: User = Depends(writer)):
    est = _draft(db, estimate_id)
    est.status = "discarded"
    db.commit()
    return {"ok": True}


# ------------------------------------------------------ sending to NetSuite
from pydantic import BaseModel  # noqa: E402

from ..models import Entity, Job  # noqa: E402
from ..netsuite import NetSuiteError  # noqa: E402
from ..services import estimate_push as P  # noqa: E402


class PushBody(BaseModel):
    model_config = {"extra": "forbid"}
    entity_id: int
    netsuite_customer_id: int | None = None
    create_customer: bool = False
    acknowledge_warnings: bool = False


@router.get("/estimates/{estimate_id}/push")
def push_check(estimate_id: int, db: Session = Depends(get_db), _: User = Depends(member)):
    """Everything the Send panel needs: is it switched on, who can be billed, what blocks it, what to know."""
    est = _est(db, estimate_id)
    job = db.get(Job, est.job_id)
    return {
        "configured": settings.netsuite_write_configured,
        "bill_to": P.bill_to_options(db, job),
        **P.check(db, est),
        "netsuite_estimate_id": est.netsuite_estimate_id,
        "account": settings.ns_account,
    }


@router.get("/entities/{entity_id}/netsuite-customers")
def netsuite_customers(entity_id: int, db: Session = Depends(get_db), _: User = Depends(writer)):
    if not settings.netsuite_write_configured:
        raise HTTPException(409, "Sending to NetSuite isn't switched on yet.")
    ent = db.get(Entity, entity_id)
    if ent is None:
        raise HTTPException(404, "Not found.")
    try:
        _, ql = P.write_client()
        return P.find_customers(ql, ent)
    except NetSuiteError as exc:
        raise HTTPException(502, f"Couldn't search NetSuite customers. {exc}") from exc


@router.post("/estimates/{estimate_id}/push")
def push_estimate(estimate_id: int, body: PushBody, db: Session = Depends(get_db), user: User = Depends(writer)):
    if not settings.netsuite_write_configured:
        raise HTTPException(409, "Sending to NetSuite isn't switched on yet. Add the NetSuite write keys on Railway.")
    est = _draft(db, estimate_id)
    try:
        P.push(db, est, body.entity_id, body.netsuite_customer_id, body.create_customer, body.acknowledge_warnings, user)
    except NetSuiteError as exc:
        db.rollback()
        raise HTTPException(502, f"NetSuite said no. {exc}") from exc
    db.commit()
    return estimate_out(db, est)
