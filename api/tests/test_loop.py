"""The loop: every event a next step, nothing goes quiet, bad news reaches the rep."""

from datetime import datetime, timedelta, timezone

from conftest import new_job, step


def _first_task(actor, job_id):
    return [t for t in actor.get(f"/api/jobs/{job_id}").json()["tasks"] if t["status"] == "open"][0]


def test_an_event_without_a_next_step_is_refused(jay):
    job = new_job(jay)
    r = jay.post(f"/api/jobs/{job['id']}/events", json={"kind": "contact", "summary": "Called Rifky"})
    assert r.status_code == 422


def test_an_event_creates_its_next_step(jay, office):
    job = new_job(jay)
    r = jay.post(
        f"/api/jobs/{job['id']}/events",
        json={"kind": "contact", "channel": "phone", "summary": "Rifky wants samples", "next_step": step(office.id, "Send samples")},
    )
    assert r.status_code == 201, r.text
    titles = [t["title"] for t in jay.get(f"/api/jobs/{job['id']}").json()["tasks"]]
    assert "Send samples" in titles


def test_finishing_the_last_open_step_requires_a_new_one(jay):
    job = new_job(jay)
    task = _first_task(jay, job["id"])
    r = jay.post(f"/api/tasks/{task['id']}/complete", json={"outcome": "done"})
    assert r.status_code == 422
    r = jay.post(f"/api/tasks/{task['id']}/complete", json={"outcome": "done", "next_step": step(jay.id, "Book visit")})
    assert r.status_code == 200 and r.json()["next_task"]["title"] == "Book visit"


def test_finishing_a_step_when_other_work_is_open_needs_no_new_one(jay, office):
    job = new_job(jay)
    jay.post(f"/api/jobs/{job['id']}/tasks", json=step(office.id, "Check stock"))
    task = _first_task(jay, job["id"])
    assert jay.post(f"/api/tasks/{task['id']}/complete", json={"outcome": "done"}).status_code == 200


def test_bad_answer_from_the_office_lands_on_the_rep(jay, office):
    job = new_job(jay)
    t = jay.post(f"/api/jobs/{job['id']}/tasks", json=step(office.id, "Check vestibule tile")).json()
    assert office.post(f"/api/tasks/{t['id']}/complete", json={"outcome": "bad_answer", "note": "Discontinued"}).status_code == 422
    r = office.post(
        f"/api/tasks/{t['id']}/complete",
        json={"outcome": "bad_answer", "note": "Discontinued", "next_step": step(jay.id, "Tell Rifky")},
    )
    assert r.status_code == 200
    dash = jay.get("/api/dashboard/rep").json()
    assert [w["title"] for w in dash["went_wrong"]] == ["Check vestibule tile"]
    jay.post(f"/api/tasks/{t['id']}/acknowledge")
    assert jay.get("/api/dashboard/rep").json()["counts"]["went_wrong"] == 0


def test_blocked_needs_a_note_and_stays_open(jay, office):
    job = new_job(jay)
    t = jay.post(f"/api/jobs/{job['id']}/tasks", json=step(office.id, "Call supplier")).json()
    assert office.post(f"/api/tasks/{t['id']}/complete", json={"outcome": "blocked"}).status_code == 422
    office.post(f"/api/tasks/{t['id']}/complete", json={"outcome": "blocked", "note": "Supplier closed till Monday"})
    detail = jay.get(f"/api/jobs/{job['id']}").json()
    assert detail["open_tasks"] == 2  # blocked still counts as open work
    assert jay.post(f"/api/tasks/{t['id']}/reopen").json()["status"] == "open"


def test_a_task_needs_an_active_assignee(boss, jay):
    pending = boss.client.post("/api/auth/dev", json={"email": "p@hstile.com"}).json()["user"]
    job = new_job(jay)
    r = jay.post(f"/api/jobs/{job['id']}/tasks", json=step(pending["id"]))
    assert r.status_code == 422


def test_morning_view_order_and_counts(jay, office):
    job = new_job(jay)
    today = jay.get("/api/dashboard/rep").json()["today"]
    jay.post(f"/api/jobs/{job['id']}/tasks", json=step(jay.id, "Call Rifky", due=today))
    dash = jay.get("/api/dashboard/rep").json()
    assert [d["title"] for d in dash["due"]] == ["Call Rifky"]
    assert set(dash["counts"]) == {"went_wrong", "visits_today", "due", "stuck"}


def test_a_job_with_nothing_open_is_stuck(jay):
    """The rules make this hard to reach on purpose, so force it straight in the database."""
    from app.db import SessionLocal
    from app.models import Job

    db = SessionLocal()
    quiet = Job(name="Quiet job", class_code="Monsey Showroom", rep_id=jay.id, status="active")
    db.add(quiet)
    db.commit()
    quiet_id = quiet.id
    db.close()

    assert jay.get(f"/api/jobs/{quiet_id}").json()["stuck"] is True
    dash = jay.get("/api/dashboard/rep").json()
    assert [j["id"] for j in dash["stuck"]["jobs"]] == [quiet_id]
    assert dash["counts"]["stuck"] == 1


def test_logging_a_scheduled_visit_marks_it_happened(jay):
    job = new_job(jay)
    when = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    v = jay.post(f"/api/jobs/{job['id']}/visits", json={"kind": "showroom", "starts_at": when}).json()
    assert v["showroom"] == "Monsey"  # from the rep's home showroom
    jay.post(
        f"/api/jobs/{job['id']}/events",
        json={"kind": "showroom_visit", "summary": "Walked the showroom", "scheduled_visit_id": v["id"], "next_step": step(jay.id)},
    )
    visits = jay.get(f"/api/jobs/{job['id']}").json()["visits"]
    assert visits[0]["status"] == "happened"


def test_a_missed_visit_shows_as_stuck(jay):
    job = new_job(jay)
    when = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    jay.post(f"/api/jobs/{job['id']}/visits", json={"kind": "showroom", "starts_at": when})
    dash = jay.get("/api/dashboard/rep").json()
    assert len(dash["stuck"]["missed_visits"]) == 1


def test_reschedule_points_to_the_new_visit(jay):
    job = new_job(jay)
    when = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    later = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    v = jay.post(f"/api/jobs/{job['id']}/visits", json={"kind": "site", "starts_at": when}).json()
    new = jay.post(f"/api/visits/{v['id']}/reschedule", json={"starts_at": later}).json()
    visits = {x["id"]: x for x in jay.get(f"/api/jobs/{job['id']}").json()["visits"]}
    assert visits[v["id"]]["status"] == "rescheduled" and visits[v["id"]]["rescheduled_to_id"] == new["id"]


def test_everything_tab_has_more_than_the_story(jay):
    job = new_job(jay)
    jay.patch(f"/api/jobs/{job['id']}", json={"lead_source": "designer"})
    story = jay.get(f"/api/jobs/{job['id']}/timeline").json()
    everything = jay.get(f"/api/jobs/{job['id']}/timeline", params={"everything": True}).json()
    assert len(everything) > len(story)
    edit = [e for e in everything if e["table_name"] == "jobs" and "lead_source" in e["changes"]][0]
    assert edit["changes"]["lead_source"] == [None, "designer"]
    assert edit["user_id"] == jay.id


def test_the_same_person_twice_on_an_event_is_fine(jay):
    from conftest import new_entity

    kisch = new_entity(jay, "Pinches Kisch")
    job = new_job(jay, people=[{"entity_id": kisch["id"], "role": "owner"}, {"entity_id": kisch["id"], "role": "pm"}],
                  first_event={"kind": "contact", "summary": "Called"})
    r = jay.post(
        f"/api/jobs/{job['id']}/events",
        json={"kind": "contact", "summary": "Again", "people": [kisch["id"], kisch["id"]], "next_step": step(jay.id)},
    )
    assert r.status_code == 201


def test_visit_story_line_is_in_new_york_time(jay):
    job = new_job(jay)
    jay.post(f"/api/jobs/{job['id']}/visits", json={"kind": "showroom", "starts_at": "2031-06-02T18:30:00+00:00"})
    story = [e["summary"] for e in jay.get(f"/api/jobs/{job['id']}/timeline").json()]
    assert "Showroom visit scheduled for Jun 2, 2:30 PM" in story


def test_unknown_api_path_is_a_json_404(client):
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.json()["detail"]


def test_management_overview(boss, jay, office):
    from app.db import SessionLocal
    from app.models import AuditLog

    job = new_job(jay)
    t = jay.post(f"/api/jobs/{job['id']}/tasks", json=step(office.id, "Check stock", due="2020-01-01")).json()
    assert t["id"]
    assert jay.get("/api/dashboard/management").status_code == 403
    m = boss.get("/api/dashboard/management").json()
    office_row = [p for p in m["people"] if p["user_id"] == office.id][0]
    assert office_row["overdue"] == 1 and m["people"][0]["user_id"] == office.id  # most behind first
    assert m["by_class"]["Monsey Showroom"]["active"] == 1 and m["totals"]["quiet"] == 0
    # Nothing touched in three weeks: quiet.
    db = SessionLocal()
    db.query(AuditLog).filter(AuditLog.job_id == job["id"]).update({"at": AuditLog.at - __import__("datetime").timedelta(days=21)})
    db.commit()
    db.close()
    assert [q["id"] for q in boss.get("/api/dashboard/management").json()["quiet"]] == [job["id"]]
    jay.post(f"/api/jobs/{job['id']}/lose", json={"reason": "price"})
    assert boss.get("/api/dashboard/management").json()["losses"] == {"price": 1}
