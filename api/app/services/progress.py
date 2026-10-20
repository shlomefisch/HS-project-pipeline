"""How far along a job is, as a row of stages: what the progress tiles show."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Area, CandidateTag, Estimate
from .availability import GOOD

STAGES = [
    ("lead", "Lead"),
    ("selection", "Selection"),
    ("footage", "Footage"),
    ("availability", "Availability"),
    ("estimate", "Estimate"),
    ("order", "Order"),
]


def for_jobs(db: Session, job_ids: list[int]) -> dict[int, dict]:
    """{job_id: {"stages": [{key, label, done}], "done": n, "current": label}} in a few queries."""
    if not job_ids:
        return {}
    areas: dict[int, list[Area]] = {}
    for a in db.scalars(select(Area).where(Area.job_id.in_(job_ids), Area.status.in_(("open", "decided")))):
        areas.setdefault(a.job_id, []).append(a)
    chosen: dict[int, list[CandidateTag]] = {}
    for t in db.scalars(select(CandidateTag).where(CandidateTag.job_id.in_(job_ids), CandidateTag.status == "chosen")):
        chosen.setdefault(t.area_id, []).append(t)
    est: dict[int, set[str]] = {}
    for jid, status in db.execute(select(Estimate.job_id, Estimate.status).where(Estimate.job_id.in_(job_ids), Estimate.status != "discarded")):
        est.setdefault(jid, set()).add(status)

    out = {}
    for jid in job_ids:
        live = areas.get(jid, [])
        tags = [t for a in live for t in chosen.get(a.id, [])]
        done = {
            "lead": True,
            "selection": bool(live) and all(chosen.get(a.id) for a in live),
            "footage": bool(live) and all(a.footage is not None for a in live),
            "availability": bool(tags) and all(t.avail_status in GOOD for t in tags),
            "estimate": bool(est.get(jid)),
            "order": "pushed" in est.get(jid, set()),
        }
        # A stage only counts once the ones before it are done: the row fills from the left.
        filled, run = [], True
        for key, label in STAGES:
            run = run and done[key]
            filled.append({"key": key, "label": label, "done": run})
        n = sum(s["done"] for s in filled)
        out[jid] = {"stages": filled, "done": n, "current": STAGES[min(n, len(STAGES) - 1)][1]}
    return out
