"""Orders on a job: placing, moving through the stages, the closing checklist,
quantity changes after the order, and closing the job."""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import member, writer
from ..db import get_db
from ..models import Estimate, EstimateArea, EstimateLine, Job, Order, OrderChange, User
from ..schemas import _In, _strip
from ..serialize import row
from ..services import orders as O
from ..services.jobs import get_job

router = APIRouter(tags=["orders"])


class PlaceByHand(_In):
    netsuite_ref: str | None = None

    _s = field_validator("netsuite_ref", mode="before")(_strip)


class Approve(_In):
    handler_id: int
    netsuite_order_ref: str | None = None

    _s = field_validator("netsuite_order_ref", mode="before")(_strip)


class Tick(_In):
    check: str
    done: bool = True


class Lose(_In):
    reason: str

    _s = field_validator("reason", mode="before")(_strip)


class QtyChange(_In):
    line_id: int
    quantity: Decimal = Field(ge=0)
    reason: str

    _s = field_validator("reason", mode="before")(_strip)


def order_out(db: Session, o: Order) -> dict:
    d = row(o)
    lines = list(db.scalars(select(EstimateLine).where(EstimateLine.estimate_id == o.estimate_id).order_by(EstimateLine.sort_order)))
    d["lines"] = [{**row(ln), "amount": float(round(ln.price * ln.quantity, 2)) if ln.price is not None and ln.quantity is not None else None} for ln in lines]
    d["total"] = round(sum(x["amount"] or 0 for x in d["lines"]), 2)
    d["area_ids"] = list(db.scalars(select(EstimateArea.area_id).where(EstimateArea.estimate_id == o.estimate_id)))
    d["changes"] = [row(c) for c in db.scalars(select(OrderChange).where(OrderChange.order_id == o.id).order_by(OrderChange.created_at.desc()))]
    d["checks"] = {k: getattr(o, col).isoformat() if getattr(o, col) else None for k, (col, _) in O.CHECKS.items()}
    d["check_labels"] = {k: label for k, (_, label) in O.CHECKS.items()}
    return d


@router.get("/jobs/{job_id}/orders")
def job_orders(job_id: int, db: Session = Depends(get_db), _: User = Depends(member)):
    get_job(db, job_id)
    return [order_out(db, o) for o in db.scalars(select(Order).where(Order.job_id == job_id).order_by(Order.id.desc()))]


@router.post("/estimates/{estimate_id}/sent-by-hand", status_code=201)
def place_by_hand(estimate_id: int, body: PlaceByHand, db: Session = Depends(get_db), user: User = Depends(writer)):
    """The estimate was entered in NetSuite by hand: it becomes an order here."""
    est = db.get(Estimate, estimate_id)
    if est is None:
        raise HTTPException(404, "Estimate not found.")
    if est.status != "draft":
        raise HTTPException(409, "This estimate has already gone out.")
    o = O.place(db, est, user, body.netsuite_ref, by_hand=True)
    db.commit()
    return order_out(db, o)


def _order(db: Session, order_id: int) -> Order:
    o = db.get(Order, order_id)
    if o is None:
        raise HTTPException(404, "Order not found.")
    return o


@router.post("/orders/{order_id}/approve")
def approve(order_id: int, body: Approve, db: Session = Depends(get_db), user: User = Depends(writer)):
    o = O.approve(db, _order(db, order_id), body.handler_id, body.netsuite_order_ref, user)
    db.commit()
    return order_out(db, o)


@router.post("/orders/{order_id}/ready")
def ready(order_id: int, db: Session = Depends(get_db), user: User = Depends(writer)):
    o = O.ready(db, _order(db, order_id), user)
    db.commit()
    return order_out(db, o)


@router.post("/orders/{order_id}/check")
def tick(order_id: int, body: Tick, db: Session = Depends(get_db), user: User = Depends(writer)):
    o = O.tick(db, _order(db, order_id), body.check, body.done, user)
    db.commit()
    return order_out(db, o)


@router.post("/orders/{order_id}/close")
def close(order_id: int, db: Session = Depends(get_db), user: User = Depends(writer)):
    o = O.close(db, _order(db, order_id), user)
    db.commit()
    return order_out(db, o)


@router.post("/orders/{order_id}/lose")
def lose(order_id: int, body: Lose, db: Session = Depends(get_db), user: User = Depends(writer)):
    o = O.lose(db, _order(db, order_id), body.reason or "", user)
    db.commit()
    return order_out(db, o)


@router.post("/orders/{order_id}/quantity")
def change_quantity(order_id: int, body: QtyChange, db: Session = Depends(get_db), user: User = Depends(writer)):
    o = _order(db, order_id)
    O.change_quantity(db, o, body.line_id, body.quantity, body.reason or "", user)
    db.commit()
    return order_out(db, o)


@router.post("/jobs/{job_id}/close")
def close_job(job_id: int, db: Session = Depends(get_db), user: User = Depends(writer)):
    from .jobs import job_detail

    job = O.close_job(db, get_job(db, job_id), user)
    db.commit()
    return job_detail(db, job)
