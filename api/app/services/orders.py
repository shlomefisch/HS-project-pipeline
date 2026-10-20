"""Orders: what happens after the estimate goes out.

negotiating -> processing (sales order made; the handler is picked here)
            -> delivery (available for delivery)
            -> closing (delivered; the checklist runs)
            -> closed (all four checks: delivered, returns, credits, paid)
An order can also be lost. A job closes only when every order is closed (or
lost) and every area is delivered or dropped — an area on hold keeps it open.
"""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Area, Estimate, EstimateArea, EstimateLine, Job, Order, OrderChange, Task, User
from ..rules.constants import TASK_OPEN
from ..timeutil import now
from .tasks import active_user

OPEN_STAGES = ("negotiating", "processing", "delivery", "closing")
CHECKS = {
    "delivered": ("chk_delivered", "Everything delivered"),
    "returns": ("chk_returns", "All returns taken back"),
    "credits": ("chk_credits", "All credits issued"),
    "paid": ("chk_paid", "Balance paid in full"),
}


def _templates(db: Session, job: Job, trigger: str, by: User, order: Order) -> None:
    from .templates import apply

    apply(db, job, trigger, by, order=order)


def place(db: Session, est: Estimate, by: User, netsuite_ref: str | None, by_hand: bool) -> Order:
    """The estimate went out: it becomes an order, and its areas are ordered."""
    job = db.get(Job, est.job_id)
    if est.status == "discarded":
        raise HTTPException(409, "This estimate was discarded.")
    if db.scalar(select(Order.id).where(Order.estimate_id == est.id)):
        raise HTTPException(409, "This estimate is already an order.")
    if est.status == "draft":
        est.status, est.pushed_at = "pushed", now()
    order = Order(job_id=job.id, estimate_id=est.id, stage="negotiating", sent_by_hand=by_hand,
                  netsuite_estimate_ref=netsuite_ref or (str(est.netsuite_estimate_id) if est.netsuite_estimate_id else None),
                  created_by=by.id)
    db.add(order)
    db.flush()
    for ea in db.scalars(select(EstimateArea).where(EstimateArea.estimate_id == est.id)):
        area = db.get(Area, ea.area_id)
        if area is not None and area.status in ("open", "decided"):
            area.status = "ordered"
    _templates(db, job, "order_placed", by, order)
    return order


def _order(db: Session, order_id: int) -> Order:
    o = db.get(Order, order_id)
    if o is None:
        raise HTTPException(404, "Order not found.")
    return o


def approve(db: Session, o: Order, handler_id: int, netsuite_order_ref: str | None, by: User) -> Order:
    """Sales order made. The rep confirms and picks who handles it from here."""
    if o.stage != "negotiating":
        raise HTTPException(409, "Only an order still being negotiated can be approved.")
    active_user(db, handler_id, "handler")
    o.stage, o.handler_id, o.netsuite_order_ref = "processing", handler_id, netsuite_order_ref
    _templates(db, db.get(Job, o.job_id), "order_approved", by, o)
    return o


def ready(db: Session, o: Order, by: User) -> Order:
    if o.stage != "processing":
        raise HTTPException(409, "Only an order in processing can be marked ready for delivery.")
    o.stage = "delivery"
    _templates(db, db.get(Job, o.job_id), "order_delivery", by, o)
    return o


def tick(db: Session, o: Order, check: str, done: bool, by: User) -> Order:
    if check not in CHECKS:
        raise HTTPException(422, "Unknown check.")
    if o.stage not in ("processing", "delivery", "closing"):
        raise HTTPException(409, "The closing checks are for an order that's been approved.")
    col, _ = CHECKS[check]
    setattr(o, col, now() if done else None)
    if check == "delivered" and done and o.stage in ("processing", "delivery"):
        o.stage = "closing"
        for ea in db.scalars(select(EstimateArea).where(EstimateArea.estimate_id == o.estimate_id)):
            area = db.get(Area, ea.area_id)
            if area is not None and area.status == "ordered":
                area.status = "delivered"
        _templates(db, db.get(Job, o.job_id), "order_closing", by, o)
    return o


def close(db: Session, o: Order, by: User) -> Order:
    if o.stage != "closing":
        raise HTTPException(409, "An order closes from closing, once it's delivered.")
    missing = [label for key, (col, label) in CHECKS.items() if getattr(o, col) is None]
    if missing:
        raise HTTPException(422, "Not done yet: " + ", ".join(missing) + ".")
    o.stage, o.closed_at = "closed", now()
    # Nothing left hanging on a closed order.
    for t in db.scalars(select(Task).where(Task.order_id == o.id, Task.status.in_(TASK_OPEN))):
        t.status, t.outcome_note, t.completed_at, t.completed_by = "skipped", "Order closed", now(), by.id
    return o


def lose(db: Session, o: Order, reason: str, by: User) -> Order:
    if o.stage not in OPEN_STAGES:
        raise HTTPException(409, "This order is already finished.")
    if not reason:
        raise HTTPException(422, "Say why the order was lost.")
    o.stage, o.lost_reason, o.closed_at = "lost", reason, now()
    for t in db.scalars(select(Task).where(Task.order_id == o.id, Task.status.in_(TASK_OPEN))):
        t.status, t.outcome_note, t.completed_at, t.completed_by = "skipped", f"Order lost: {reason}", now(), by.id
    return o


def change_quantity(db: Session, o: Order, line_id: int, new_qty, reason: str, by: User) -> OrderChange:
    """A quantity up or down on something already ordered: a change to that order, recorded in full."""
    if o.stage not in OPEN_STAGES:
        raise HTTPException(409, "This order is finished — a change now is a new order.")
    ln = db.get(EstimateLine, line_id)
    if ln is None or ln.estimate_id != o.estimate_id:
        raise HTTPException(422, "That line isn't on this order.")
    if not reason:
        raise HTTPException(422, "Say why the quantity changed.")
    if ln.quantity is not None and new_qty == ln.quantity:
        raise HTTPException(422, "That's the same quantity.")
    ch = OrderChange(order_id=o.id, job_id=o.job_id, line_id=ln.id, old_quantity=ln.quantity or 0, new_quantity=new_qty,
                     reason=reason, created_by=by.id)
    ln.quantity = new_qty
    db.add(ch)
    return ch


def close_job(db: Session, job: Job, by: User) -> Job:
    """Closed means done: nothing open, nothing owed, nothing coming back."""
    if job.status == "closed":
        raise HTTPException(409, "This job is already closed.")
    open_orders = db.scalars(select(Order).where(Order.job_id == job.id, Order.stage.in_(OPEN_STAGES))).all()
    if open_orders:
        raise HTTPException(422, f"{len(open_orders)} order(s) still open. Close them first.")
    waiting = [a.name for a in db.scalars(select(Area).where(Area.job_id == job.id, Area.status.in_(("open", "decided", "on_hold", "ordered"))))]
    if waiting:
        raise HTTPException(422, "These areas aren't delivered or dropped yet: " + ", ".join(waiting) + ". An area on hold keeps the job open.")
    if not db.scalar(select(Order.id).where(Order.job_id == job.id, Order.stage == "closed")):
        raise HTTPException(422, "Nothing was ever delivered on this job. If it's over, mark it lost instead.")
    for t in db.scalars(select(Task).where(Task.job_id == job.id, Task.status.in_(TASK_OPEN))):
        t.status, t.outcome_note, t.completed_at, t.completed_by = "skipped", "Job closed", now(), by.id
    job.status, job.closed_at = "closed", now()
    return job
