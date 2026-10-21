"""Away (a cover holds everything, and gets anything new) and gone (hand over, then deactivate)."""

from datetime import date, timedelta

from conftest import make_user, new_job, step


def _today(actor):
    return date.fromisoformat(actor.get("/api/dashboard/rep").json()["today"])


def test_away_hands_everything_to_the_cover_and_back(boss, jay, office):
    moshe = make_user(boss, "moshe@hstile.com", "Moshe", "rep")
    job = new_job(jay)
    t0 = _today(jay)
    boss.put("/api/settings", json={"takeoff_user_id": jay.id})
    r = boss.post(f"/api/users/{jay.id}/away", json={"cover_id": moshe.id, "starts_on": t0.isoformat(), "ends_on": (t0 + timedelta(days=7)).isoformat()})
    assert r.status_code == 201, r.text
    assert r.json()["current"]["status"] == "active"
    assert r.json()["counts"] == {"jobs": 0, "tasks": 0, "visits": 0, "orders": 0, "takeoff": 0}
    detail = jay.get(f"/api/jobs/{job['id']}").json()
    assert detail["rep_id"] == moshe.id and detail["covering_for_id"] == jay.id
    assert all(t["assignee_id"] == moshe.id and t["covering_for_id"] == jay.id for t in detail["tasks"] if t["status"] == "open")
    assert boss.get("/api/settings").json()["takeoff_user_id"] == moshe.id

    # Anything new aimed at Jay goes to Moshe, marked.
    t = office.post(f"/api/jobs/{job['id']}/tasks", json=step(jay.id, "Call the designer")).json()
    assert t["assignee_id"] == moshe.id and t["covering_for_id"] == jay.id

    # Moshe finishes one while covering: it stays credited to him.
    office.post(f"/api/tasks/{t['id']}/complete", json={"outcome": "done"})

    back = boss.post(f"/api/users/{jay.id}/back").json()
    assert back["current"] is None and back["history"][0]["status"] == "ended"
    detail = jay.get(f"/api/jobs/{job['id']}").json()
    assert detail["rep_id"] == jay.id and detail["covering_for_id"] is None
    tasks = {x["title"]: x for x in detail["tasks"]}
    assert tasks["Call the designer"]["assignee_id"] == moshe.id and tasks["Call the designer"]["status"] == "done"
    assert all(x["assignee_id"] == jay.id for x in detail["tasks"] if x["status"] == "open")
    assert boss.get("/api/settings").json()["takeoff_user_id"] == jay.id


def test_a_future_away_starts_on_its_day(boss, jay):
    from app.db import SessionLocal
    from app.models import Absence
    from app.services import absences

    moshe = make_user(boss, "moshe@hstile.com", "Moshe", "rep")
    new_job(jay)
    t0 = _today(jay)
    r = boss.post(f"/api/users/{jay.id}/away", json={"cover_id": moshe.id, "starts_on": (t0 + timedelta(days=3)).isoformat(), "ends_on": (t0 + timedelta(days=5)).isoformat()})
    assert r.json()["current"]["status"] == "planned" and r.json()["counts"]["jobs"] == 1
    # Pretend the day has come.
    db = SessionLocal()
    a = db.query(Absence).one()
    a.starts_on = t0
    db.commit()
    absences.apply_due(db)
    db.commit()
    db.close()
    assert boss.get(f"/api/users/{jay.id}/away-or-gone").json()["counts"]["jobs"] == 0


def test_cover_rules(boss, jay, office):
    t0 = _today(jay).isoformat()
    assert boss.post(f"/api/users/{jay.id}/away", json={"cover_id": jay.id, "starts_on": t0, "ends_on": t0}).status_code == 422
    boss.post(f"/api/users/{office.id}/away", json={"cover_id": boss.id, "starts_on": t0, "ends_on": t0})
    r = boss.post(f"/api/users/{jay.id}/away", json={"cover_id": office.id, "starts_on": t0, "ends_on": t0})
    assert r.status_code == 422 and "away too" in r.json()["detail"]
    assert jay.post(f"/api/users/{office.id}/back").status_code == 403


def test_gone_means_hand_over_then_deactivate(boss, jay):
    moshe = make_user(boss, "moshe@hstile.com", "Moshe", "rep")
    a, b = new_job(jay, name="Job A"), new_job(jay, name="Job B")
    r = boss.patch(f"/api/users/{jay.id}", json={"active": False})
    assert r.status_code == 409 and "open job" in r.json()["detail"]
    screen = boss.post(f"/api/users/{jay.id}/hand-over", json={"to_user_id": moshe.id, "what": "jobs", "ids": [a["id"]]}).json()
    assert screen["counts"]["jobs"] == 1  # one by one
    boss.post(f"/api/users/{jay.id}/hand-over", json={"to_user_id": moshe.id, "what": "jobs"})
    screen = boss.post(f"/api/users/{jay.id}/hand-over", json={"to_user_id": moshe.id, "what": "tasks"}).json()
    assert screen["counts"] == {"jobs": 0, "tasks": 0, "visits": 0, "orders": 0, "takeoff": 0}
    assert boss.patch(f"/api/users/{jay.id}", json={"active": False}).status_code == 200
    assert jay.get(f"/api/jobs/{b['id']}").status_code == 401  # signed out for good


def test_a_cover_who_goes_away_too_still_sends_everything_home(boss, jay, office):
    """Jay away (Moshe covers), then Moshe away (Office covers). Jay comes back first: all of Jay's work is home."""
    moshe = make_user(boss, "moshe@hstile.com", "Moshe", "rep")
    job = new_job(jay)
    t0 = _today(jay).isoformat()
    later = (_today(jay) + timedelta(days=5)).isoformat()
    boss.put("/api/settings", json={"takeoff_user_id": jay.id})
    boss.post(f"/api/users/{jay.id}/away", json={"cover_id": moshe.id, "starts_on": t0, "ends_on": later})
    boss.post(f"/api/users/{moshe.id}/away", json={"cover_id": office.id, "starts_on": t0, "ends_on": later})
    assert jay.get(f"/api/jobs/{job['id']}").json()["rep_id"] == office.id
    boss.post(f"/api/users/{jay.id}/back")
    detail = jay.get(f"/api/jobs/{job['id']}").json()
    assert detail["rep_id"] == jay.id and detail["covering_for_id"] is None
    assert all(t["assignee_id"] == jay.id for t in detail["tasks"] if t["status"] == "open")
    assert boss.get("/api/settings").json()["takeoff_user_id"] == jay.id


def test_the_cover_cant_be_deactivated_mid_away(boss, jay):
    moshe = make_user(boss, "moshe@hstile.com", "Moshe", "rep")
    t0 = _today(jay).isoformat()
    boss.post(f"/api/users/{jay.id}/away", json={"cover_id": moshe.id, "starts_on": t0, "ends_on": t0})
    r = boss.patch(f"/api/users/{moshe.id}", json={"active": False})
    assert r.status_code == 409 and "cover" in r.json()["detail"]


def test_reassigning_by_hand_respects_away_and_ends_covering(boss, jay, office):
    moshe = make_user(boss, "moshe@hstile.com", "Moshe", "rep")
    job = new_job(jay)
    t = jay.post(f"/api/jobs/{job['id']}/tasks", json=step(jay.id, "Measure the hall")).json()
    t0 = _today(jay).isoformat()
    boss.post(f"/api/users/{office.id}/away", json={"cover_id": moshe.id, "starts_on": t0, "ends_on": t0})
    r = jay.patch(f"/api/tasks/{t['id']}", json={"assignee_id": office.id}).json()
    assert r["assignee_id"] == moshe.id and r["covering_for_id"] == office.id
    r = jay.patch(f"/api/tasks/{t['id']}", json={"assignee_id": jay.id}).json()
    assert r["assignee_id"] == jay.id and r["covering_for_id"] is None


def test_temporary_password_people_must_pick_their_own_first(client, boss):
    boss.post("/api/users", json={"email": "dina@hstile.com", "name": "Dina", "role": "rep", "password": "temp-pass-1"})
    tok = client.post("/api/auth/login", json={"email": "dina@hstile.com", "password": "temp-pass-1"}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/api/jobs", headers=h).status_code == 403
    assert client.get("/api/auth/me", headers=h).status_code == 200
