"""Who gets buzzed, and what happens when a phone has gone away."""

from conftest import new_job, step
from app.services import push


def _db():
    from app.db import SessionLocal

    return SessionLocal()


def test_a_step_from_someone_else_buzzes_its_owner(jay, office):
    job = new_job(jay)
    t = office.post(f"/api/jobs/{job['id']}/tasks", json={**step(jay.id, "Call the designer"), "severity": "notify"}).json()
    db = _db()
    msgs = push.plan_message(db, "task", t["id"])
    db.close()
    assert msgs[0][0] == jay.id and "Call the designer" in msgs[0][2] and msgs[0][3] == f"/#/jobs/{job['id']}"


def test_a_bad_answer_buzzes_the_rep_but_not_when_the_rep_did_it(jay, office):
    job = new_job(jay)
    t = jay.post(f"/api/jobs/{job['id']}/tasks", json=step(office.id, "Check stock")).json()
    office.post(f"/api/tasks/{t['id']}/complete", json={"outcome": "bad_answer", "note": "Discontinued", "next_step": step(jay.id, "Tell Rifky")})
    db = _db()
    msgs = push.plan_message(db, "bad", t["id"])
    db.close()
    assert msgs[0][0] == jay.id and msgs[0][1].startswith("Bad answer") and msgs[0][4] is True


def test_someone_else_logging_on_my_job_tells_me(jay, office):
    job = new_job(jay)
    office.post(f"/api/jobs/{job['id']}/events", json={"kind": "contact", "summary": "Installer called about delivery", "next_step": step(jay.id)})
    from app.models import Event

    db = _db()
    e = db.query(Event).filter(Event.summary == "Installer called about delivery").one()
    msgs = push.plan_message(db, "event", e.id)
    db.close()
    assert msgs and msgs[0][0] == jay.id and "Installer called" in msgs[0][2]


def test_subscribe_and_a_gone_phone_is_forgotten(client, jay):
    sub = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "keys": {"p256dh": "BPk", "auth": "xyz"}}
    assert jay.get("/api/push/key").json()["key"]
    assert jay.post("/api/push/subscribe", json=sub).json()["phones"] == 1
    assert jay.post("/api/push/subscribe", json=sub).json()["phones"] == 1  # same phone twice is one

    class Gone(Exception):
        response = type("R", (), {"status_code": 410})()

    sent = []

    def sender(**kw):
        sent.append(kw)
        raise Gone()

    db = _db()
    assert push.deliver(db, {"user_id": jay.id, "title": "t", "body": "b", "url": "/", "urgent": False}, sender=sender) == 0
    db.commit()
    db.close()
    assert len(sent) == 1 and jay.get("/api/push/status").json()["phones"] == 0
