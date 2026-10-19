"""Demo data: 21 Mountain Rd, the people on it, and a stand-in item list.

    python -m scripts.seed_demo

Safe to run twice — it skips anything already there. For testing only;
the real item list will come from the NetSuite sync.
"""

from datetime import timedelta

from sqlalchemy import select

from app import audit  # noqa: F401
from app.db import SessionLocal
from app.models import Area, Candidate, CandidateTag, Entity, Event, EventPerson, Item, Job, JobRole, Task, User
from app.services.people import apply_norms
from app.timeutil import today

STAND_IN_ITEMS = [
    (100101, "Calacatta Gold Porcelain 12x24 Matte", "CAL-1224-M", "12x24", "Matte"),
    (100102, "Calacatta Gold Porcelain 24x48 Polished", "CAL-2448-P", "24x48", "Polished"),
    (100203, "Bianco Carrara Marble 12x24 Honed", "BC-1224-H", "12x24", "Honed"),
    (100310, "Nero Marquina Hex 3in", "NM-HEX3", "3in hex", "Polished"),
    (100422, "Grey Concrete Look 24x24", "GCL-2424", "24x24", "Matte"),
    (100530, "Limestone Look 18x18 Beige", "LL-1818-B", "18x18", "Matte"),
    (100611, "White Subway 3x6 Gloss", "WS-36-G", "3x6", "Gloss"),
    (100712, "Oak Wood Look Plank 8x48", "OWL-848", "8x48", "Matte"),
]


def _user(db, email, name, role, showroom, klass, admin=False):
    u = db.scalar(select(User).where(User.email == email))
    if u is None:
        u = User(email=email, name=name, role=role, home_showroom=showroom, default_class=klass, is_admin=admin, active=True)
        db.add(u)
        db.flush()
    return u


def _entity(db, name, kind="person", phone=None, email=None):
    e = db.scalar(select(Entity).where(Entity.name == name))
    if e is None:
        e = Entity(name=name, kind=kind, phone=phone, email=email, active=True)
        apply_norms(e)
        db.add(e)
        db.flush()
    return e


def main() -> None:
    db = SessionLocal()
    try:
        for nid, name, sku, size, finish in STAND_IN_ITEMS:
            if db.get(Item, nid) is None:
                db.add(Item(netsuite_id=nid, name=name, sku=sku, size=size, finish=finish, active=True))

        jay = _user(db, "jay@hstile.com", "Jay S.", "rep", "Monsey", "Monsey Showroom")
        office = _user(db, "office@hstile.com", "Office (demo)", "back_office", "Monsey", "Monsey Showroom")
        db.info["user_id"] = jay.id

        if db.scalar(select(Job).where(Job.name == "21 Mountain Rd")):
            db.commit()
            print("Demo job already there — items and users checked.")
            return

        rifky = _entity(db, "Rifky Freund", phone="845-555-0101")
        kisch = _entity(db, "Pinches Kisch", phone="845-555-0102")
        atoz = _entity(db, "AtoZ Construction", kind="company", phone="845-555-0103")

        job = Job(name="Kisch – Mountain", class_code="Monsey Showroom", lead_source="designer", rep_id=jay.id, status="active", created_by=jay.id)
        db.add(job)
        db.flush()
        for ent, role in ((rifky, "designer"), (kisch, "owner"), (atoz, "contractor")):
            db.add(JobRole(job_id=job.id, entity_id=ent.id, role=role, active=True, created_by=jay.id))
        job.default_contact_id = kisch.id
        db.flush()

        call = Event(job_id=job.id, kind="contact", channel="phone", direction="in", summary="Rifky called: coming in with Kisch from Mountain", logged_by=jay.id)
        db.add(call)
        db.flush()
        db.add(EventPerson(event_id=call.id, entity_id=rifky.id))

        # The visit happened; the job gets its real name.
        job.name, job.address = "21 Mountain Rd", "21 Mountain Rd"
        visit = Event(job_id=job.id, kind="showroom_visit", showroom="Monsey", summary="Rifky and Pinches walked the showroom — kitchen and vestibule, nothing final, samples requested", logged_by=jay.id)
        db.add(visit)
        db.flush()
        db.add_all([EventPerson(event_id=visit.id, entity_id=rifky.id), EventPerson(event_id=visit.id, entity_id=kisch.id)])

        kitchen = Area(job_id=job.id, name="Kitchen", status="open", sort_order=1, created_by=jay.id)
        vestibule = Area(job_id=job.id, name="Vestibule", status="open", sort_order=2, created_by=jay.id)
        db.add_all([kitchen, vestibule])
        db.flush()

        def cand(source, name=None, item=None, supplier=None, weeks=None):
            c = Candidate(job_id=job.id, source=source, name=name, netsuite_item_id=item, supplier=supplier, lead_time_weeks=weeks, created_by=jay.id)
            db.add(c)
            db.flush()
            return c

        cal = cand("stock", "Calacatta Gold Porcelain 12x24 Matte", 100101)
        carrara = cand("stock", "Bianco Carrara Marble 12x24 Honed", 100203)
        grey = cand("stock", "Grey Concrete Look 24x24", 100422)
        terrazzo = cand("overseas", "Italian Terrazzo 24x24 Verde", supplier="Milano Ceramiche", weeks=12)
        for c, area in ((cal, kitchen), (cal, vestibule), (carrara, kitchen), (grey, vestibule), (terrazzo, vestibule)):
            db.add(CandidateTag(job_id=job.id, candidate_id=c.id, area_id=area.id, status="considering"))
        db.flush()
        decline = db.scalar(select(CandidateTag).where(CandidateTag.candidate_id == grey.id))
        decline.status, decline.reason = "declined", "Too cold next to the oak floor"

        db.add(Task(job_id=job.id, title="Send Calacatta + Carrara samples to Rifky", assignee_id=office.id, due_date=today() + timedelta(days=1), created_by=jay.id, source_event_id=visit.id))
        db.add(Task(job_id=job.id, title="Follow up with Rifky on samples", assignee_id=jay.id, due_date=today(), created_by=jay.id, source_event_id=visit.id))
        db.commit()
        print("Seeded 21 Mountain Rd with Jay S. (jay@hstile.com) and an office user (office@hstile.com).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
