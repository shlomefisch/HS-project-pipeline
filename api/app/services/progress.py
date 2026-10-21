"""How far along a job is, as a row of stages: what the progress tiles show."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Area, Candidate, CandidateTag, Estimate, Job, Order
from .availability import GOOD

STAGES = [
    ("lead", "Lead"),
    ("selection", "Selection"),
    ("footage", "Footage"),
    ("availability", "Availability"),
    ("estimate", "Estimate"),
    ("ordered", "Ordered"),
    ("delivery", "Delivery"),
    ("closed", "Closed"),
]


def for_jobs(db: Session, job_ids: list[int]) -> dict[int, dict]:
    """{job_id: {"stages": [{key, label, done}], "done": n, "current": label}} in a few queries."""
    if not job_ids:
        return {}
    areas: dict[int, list[Area]] = {}
    for a in db.scalars(select(Area).where(Area.job_id.in_(job_ids), Area.status.in_(("open", "decided")))):
        areas.setdefault(a.job_id, []).append(a)  # ordered / delivered ones are added below
    chosen: dict[int, list[CandidateTag]] = {}
    for t in db.scalars(
        select(CandidateTag).join(Candidate, Candidate.id == CandidateTag.candidate_id)
        .where(CandidateTag.job_id.in_(job_ids), CandidateTag.status == "chosen", Candidate.removed_at.is_(None))
    ):
        chosen.setdefault(t.area_id, []).append(t)
    # A lost order, and the estimate it came from, are history — not progress.
    lost_est = set(db.scalars(select(Order.estimate_id).where(Order.job_id.in_(job_ids), Order.stage == "lost")))
    est: dict[int, set[str]] = {}
    for eid, jid, status in db.execute(select(Estimate.id, Estimate.job_id, Estimate.status).where(Estimate.job_id.in_(job_ids), Estimate.status != "discarded")):
        if eid not in lost_est:
            est.setdefault(jid, set()).add(status)
    stages: dict[int, set[str]] = {}
    for jid, stage in db.execute(select(Order.job_id, Order.stage).where(Order.job_id.in_(job_ids), Order.stage != "lost")):
        stages.setdefault(jid, set()).add(stage)
    closed_jobs = set(db.scalars(select(Job.id).where(Job.id.in_(job_ids), Job.status == "closed")))
    # Ordered or delivered areas still count as selected and measured: they got there.
    for a in db.scalars(select(Area).where(Area.job_id.in_(job_ids), Area.status.in_(("ordered", "delivered")))):
        areas.setdefault(a.job_id, []).append(a)

    out = {}
    for jid in job_ids:
        every = areas.get(jid, [])
        # Areas already on an order got through selection, footage and availability;
        # what's still in front is judged on the areas still being worked.
        working = [a for a in every if a.status in ("open", "decided")]
        past = [a for a in every if a.status in ("ordered", "delivered")]
        tags = [t for a in working for t in chosen.get(a.id, [])]
        done = {
            "lead": True,
            "selection": bool(every) and all(chosen.get(a.id) for a in working),
            # The number on each chosen tile is the footage; the area's number only starts new tiles.
            "footage": (bool(tags) or bool(past)) and all(t.quantity is not None for t in tags),
            "availability": (bool(tags) or bool(past)) and all(t.avail_status in GOOD for t in tags),
            "estimate": bool(est.get(jid)),
            "ordered": bool(stages.get(jid)),
            "delivery": bool(stages.get(jid, set()) & {"delivery", "closing", "closed"}),
            "closed": jid in closed_jobs,
        }
        # A stage only counts once the ones before it are done: the row fills from the left.
        filled, run = [], True
        for key, label in STAGES:
            run = run and done[key]
            filled.append({"key": key, "label": label, "done": run})
        n = sum(s["done"] for s in filled)
        out[jid] = {"stages": filled, "done": n, "current": STAGES[min(n, len(STAGES) - 1)][1]}
    return out
