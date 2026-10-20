"""Sending an estimate to NetSuite. Creates only an estimate — never an order,
never anything further — and a customer only when none matches.

Bill-to is a person or company on the job (usually the owner). They are matched
to a NetSuite customer by email, phone or name; the rep confirms the match. The
match is remembered on the record, so the next estimate needs no search.
"""

import re

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Area, CandidateTag, Entity, Estimate, EstimateLine, Job, JobRole, User
from ..netsuite import Keys, NetSuiteError, Records, SuiteQL
from ..rules.normalize import norm_phone
from ..timeutil import now
from .availability import GOOD


def read_client() -> SuiteQL:
    return SuiteQL(Keys(settings.ns_account, settings.ns_consumer_key, settings.ns_consumer_secret, settings.ns_token_id, settings.ns_token_secret))


def write_client() -> tuple[Records, SuiteQL]:
    """Both on the write token: reads that decide a write use the same role."""
    keys = Keys(
        settings.ns_account,
        settings.ns_write_consumer_key or settings.ns_consumer_key,
        settings.ns_write_consumer_secret or settings.ns_consumer_secret,
        settings.ns_write_token_id,
        settings.ns_write_token_secret,
    )
    return Records(keys), SuiteQL(keys)


def _q(text: str) -> str:
    """A string safe inside a SuiteQL literal: no quotes, no wildcards, nothing odd."""
    return re.sub(r"[^\w @.+\-]", "", text or "").replace("'", "")[:60]


# --------------------------------------------------------- customers
def find_customers(ql: SuiteQL, ent: Entity) -> list[dict]:
    conds = []
    if ent.email:
        conds.append(f"LOWER(c.email) = '{_q(ent.email.lower())}'")
    digits = norm_phone(ent.phone) if ent.phone else None
    if digits and len(digits) >= 7:
        conds.append(f"REGEXP_REPLACE(c.phone, '[^0-9]', '') LIKE '%{digits[-7:]}'")
    name = _q(ent.name.lower())
    if len(name) >= 3:
        conds.append(f"LOWER(c.entityid) LIKE '%{name}%'")
        conds.append(f"LOWER(c.companyname) LIKE '%{name}%'")
    if not conds:
        return []
    sql = (
        "SELECT c.id AS id, c.entityid AS entityid, c.companyname AS companyname, c.email AS email, c.phone AS phone "
        f"FROM customer c WHERE c.isinactive = 'F' AND ({' OR '.join(conds)}) ORDER BY c.id DESC"
    )
    rows, _ = ql.page(sql, limit=20)
    out = []
    for r in rows:
        why = []
        if ent.email and (r.get("email") or "").lower() == ent.email.lower():
            why.append("same email")
        if digits and norm_phone(r.get("phone") or "") and norm_phone(r.get("phone"))[-7:] == digits[-7:]:
            why.append("same phone")
        if not why:
            why.append("similar name")
        out.append({
            "id": int(r["id"]),
            "name": r.get("companyname") or r.get("entityid") or f"Customer #{r['id']}",
            "number": r.get("entityid"),
            "email": r.get("email"),
            "phone": r.get("phone"),
            "why": why,
        })
    out.sort(key=lambda m: (-("same email" in m["why"]) - ("same phone" in m["why"]), m["name"]))
    return out


def create_customer(rec: Records, ent: Entity) -> int:
    body: dict = {"subsidiary": {"id": settings.ns_subsidiary_id}}
    if ent.kind == "company":
        body.update({"isPerson": False, "companyName": ent.name})
    else:
        first, _, last = ent.name.partition(" ")
        body.update({"isPerson": True, "firstName": first or ent.name, "lastName": last or "-"})
    if ent.email:
        body["email"] = ent.email
    if ent.phone:
        body["phone"] = ent.phone
    return rec.create("customer", body)


# ---------------------------------------------------------- checking
def check(db: Session, est: Estimate) -> dict:
    """What stops the push (blockers) and what the rep should know first (warnings)."""
    lines = list(db.scalars(select(EstimateLine).where(EstimateLine.estimate_id == est.id).order_by(EstimateLine.sort_order)))
    blockers, warnings = [], []
    if est.status != "draft":
        blockers.append("This estimate isn't being put together any more.")
    if not lines:
        blockers.append("There are no lines.")
    for ln in lines:
        if ln.quantity is None:
            blockers.append(f"{ln.description}: no quantity.")
        if ln.price is None:
            blockers.append(f"{ln.description}: no price.")
        if ln.netsuite_item_id is None and not settings.ns_special_item_id:
            blockers.append(f"{ln.description}: not one of our items, and no special-order item is set up in NetSuite for it.")
        tag = db.get(CandidateTag, ln.tag_id) if ln.tag_id else None
        if tag and tag.avail_status not in GOOD:
            warnings.append(f"{ln.description}: availability {tag.avail_status or 'not checked'}.")
    area_ids = {ln.area_id for ln in lines if ln.area_id}
    approx = [a.name for a in (db.get(Area, i) for i in area_ids) if a and a.footage_confidence == "approximate"]
    if approx:
        warnings.append("Approximate footage for " + ", ".join(approx) + ".")
    return {"blockers": blockers, "warnings": warnings}


def bill_to_options(db: Session, job: Job) -> list[dict]:
    """The job's people, the owner first — bill-to is usually the owner."""
    rows = db.execute(
        select(JobRole, Entity).join(Entity, Entity.id == JobRole.entity_id).where(JobRole.job_id == job.id, JobRole.active.is_(True))
    ).all()
    order = {"owner": 0, "contractor": 1, "designer": 2, "pm": 3, "installer": 4, "other": 5}
    seen, out = set(), []
    for role, ent in sorted(rows, key=lambda r: order.get(r[0].role, 9)):
        if ent.id in seen:
            continue
        seen.add(ent.id)
        out.append({"entity_id": ent.id, "name": ent.name, "role": role.role, "netsuite_customer_id": ent.netsuite_customer_id})
    return out


# ------------------------------------------------------------- push
def _class_id(ql: SuiteQL, name: str) -> int | None:
    try:
        rows, _ = ql.page(f"SELECT c.id AS id FROM classification c WHERE c.name = '{_q(name)}'", limit=1)
        return int(rows[0]["id"]) if rows else None
    except NetSuiteError:
        return None  # the estimate still goes; the department can be set in NetSuite


def push(db: Session, est: Estimate, entity_id: int, customer_id: int | None, create_new: bool, acknowledged: bool,
         by: User, clients=None) -> Estimate:
    job = db.get(Job, est.job_id)
    result = check(db, est)
    if result["blockers"]:
        raise HTTPException(422, "Can't send yet: " + " ".join(result["blockers"]))
    if result["warnings"] and not acknowledged:
        raise HTTPException(409, "Read the warnings first: " + " ".join(result["warnings"]))
    if not any(o["entity_id"] == entity_id for o in bill_to_options(db, job)):
        raise HTTPException(422, "Bill to someone on this job.")
    ent = db.get(Entity, entity_id)
    rec, ql = clients or write_client()

    external = f"pipeline-est-{est.id}"
    try:
        # Sent before, and the answer got lost? Then it's already there: don't make a second one.
        rows, _ = ql.page(f"SELECT t.id AS id FROM transaction t WHERE t.externalid = '{external}'", limit=1)
        existing = int(rows[0]["id"]) if rows else None
    except NetSuiteError:
        existing = None

    if existing is None:
        if customer_id is None:
            if ent.netsuite_customer_id and ent.netsuite_customer_id.isdigit():
                customer_id = int(ent.netsuite_customer_id)
            elif create_new:
                customer_id = create_customer(rec, ent)
            else:
                raise HTTPException(422, "Pick the NetSuite customer, or say to create a new one.")
        ent.netsuite_customer_id = str(customer_id)  # remembered for next time

        lines = list(db.scalars(select(EstimateLine).where(EstimateLine.estimate_id == est.id).order_by(EstimateLine.sort_order)))
        items = []
        for ln in lines:
            item_id = ln.netsuite_item_id or int(settings.ns_special_item_id)
            items.append({
                "item": {"id": str(item_id)},
                "quantity": float(ln.quantity),
                "price": {"id": "-1"},  # custom: the price we agreed, not the price level
                "rate": float(ln.price),
                "description": ln.description,
            })
        body = {
            "externalId": external,
            "entity": {"id": str(customer_id)},
            "memo": f"{job.name} — from Pipeline" + (f" — {est.note}" if est.note else ""),
            "item": {"items": items},
        }
        class_id = _class_id(ql, job.class_code)
        if class_id:
            body["class"] = {"id": str(class_id)}
        try:
            existing = rec.create("estimate", body)
        except NetSuiteError as exc:
            db.commit()  # keep the customer we may have just made, so a retry reuses it
            raise HTTPException(502, f"NetSuite didn't take the estimate. {exc}") from exc

    est.status, est.pushed_at, est.netsuite_estimate_id = "pushed", now(), existing
    from .orders import place

    place(db, est, by, str(existing), by_hand=False)
    return est
