"""Step templates: the usual steps appear by themselves at set moments."""

from conftest import new_job, step


def _titles(actor, job_id):
    return {t["title"]: t for t in actor.get(f"/api/jobs/{job_id}").json()["tasks"]}


def test_job_created_adds_the_usual_steps_by_playbook(boss, jay, office):
    boss.post("/api/templates", json={"trigger": "job_created", "title": "Send the welcome text", "assignee_kind": "user", "assignee_user_id": office.id, "due_days": 0})
    boss.post("/api/templates", json={"trigger": "job_created", "playbook": "projects", "title": "Ask for the plans", "due_days": 2})
    single = new_job(jay, project_type="single_family")
    titles = _titles(jay, single["id"])
    assert titles["Send the welcome text"]["assignee_id"] == office.id
    assert "Ask for the plans" not in titles  # projects only
    project = new_job(jay, name="Lake Towers", project_type="multi_unit")
    titles = _titles(jay, project["id"])
    assert titles["Ask for the plans"]["assignee_id"] == jay.id and "Send the welcome text" in titles


def test_area_decided_adds_a_step_per_area_once(boss, jay):
    boss.post("/api/templates", json={"trigger": "area_decided", "title": "Check availability"})
    job = new_job(jay)
    area = jay.post(f"/api/jobs/{job['id']}/areas", json={"name": "Kitchen"}).json()
    jay.post(f"/api/jobs/{job['id']}/candidates", json={"source": "local", "name": "Grey", "area_ids": [area["id"]]})
    tag = jay.get(f"/api/jobs/{job['id']}").json()["candidates"][0]["tags"][0]
    jay.patch(f"/api/tags/{tag['id']}", json={"status": "chosen"})
    jay.patch(f"/api/areas/{area['id']}", json={"status": "decided"})
    jay.patch(f"/api/areas/{area['id']}", json={"status": "open"})
    jay.patch(f"/api/areas/{area['id']}", json={"status": "decided"})
    titles = [t["title"] for t in jay.get(f"/api/jobs/{job['id']}").json()["tasks"]]
    assert titles.count("Check availability — Kitchen") == 1


def test_a_person_who_left_falls_back_to_the_rep(boss, jay):
    from conftest import make_user

    temp = make_user(boss, "temp@hstile.com", "Temp", "back_office")
    boss.post("/api/templates", json={"trigger": "job_created", "title": "Call back", "assignee_kind": "user", "assignee_user_id": temp.id})
    boss.patch(f"/api/users/{temp.id}", json={"active": False})
    job = new_job(jay)
    assert _titles(jay, job["id"])["Call back"]["assignee_id"] == jay.id


def test_only_admins_edit_and_removing_keeps_history(boss, jay):
    assert jay.post("/api/templates", json={"trigger": "job_created", "title": "x"}).status_code == 403
    s = boss.post("/api/templates", json={"trigger": "job_created", "title": "Old step"}).json()
    job = new_job(jay)
    boss.patch(f"/api/templates/{s['id']}", json={"active": False})
    assert boss.get("/api/templates").json()["steps"] == []
    assert "Old step" in _titles(jay, job["id"])  # the task it made stays
    assert boss.post("/api/templates", json={"trigger": "job_created", "title": "y", "assignee_kind": "user"}).status_code == 422
