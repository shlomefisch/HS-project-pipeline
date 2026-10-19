from conftest import make_user, new_entity, new_job, step


def test_a_job_needs_only_a_rep_and_one_person(jay):
    job = new_job(jay)
    assert job["rep_id"] == jay.id
    assert job["class_code"] == "Monsey Showroom"  # from the rep's default
    assert job["open_tasks"] == 1
    assert job["stuck"] is False


def test_a_job_without_a_person_is_refused(jay):
    r = jay.post("/api/jobs", json={"name": "x", "people": [], "next_step": step(jay.id)})
    assert r.status_code == 422


def test_a_job_without_a_next_step_is_refused(jay):
    rifky = new_entity(jay, "Rifky Freund")
    r = jay.post("/api/jobs", json={"name": "x", "people": [{"entity_id": rifky["id"], "role": "designer"}]})
    assert r.status_code == 422


def test_office_must_say_whose_job_it_is(boss, office):
    rifky = new_entity(office, "Rifky Freund")
    body = {"name": "x", "people": [{"entity_id": rifky["id"], "role": "designer"}], "next_step": step(office.id)}
    assert office.post("/api/jobs", json=body).status_code == 422


def test_rename_keeps_identity_and_is_on_the_story(jay):
    job = new_job(jay, name="Kisch – Mountain")
    r = jay.patch(f"/api/jobs/{job['id']}", json={"name": "21 Mountain Rd"})
    assert r.json()["id"] == job["id"]
    story = jay.get(f"/api/jobs/{job['id']}/timeline").json()
    assert any("Renamed from “Kisch – Mountain” to “21 Mountain Rd”" in (e["summary"] or "") for e in story)


def test_capped_role_replaces_the_old_holder_and_keeps_history(jay):
    job = new_job(jay)
    other = new_entity(jay, "Another Designer")
    detail = jay.post(f"/api/jobs/{job['id']}/roles", json={"entity_id": other["id"], "role": "designer"}).json()
    designers = [r for r in detail["roles"] if r["role"] == "designer"]
    assert len(designers) == 2
    active = [r for r in designers if r["active"]]
    assert len(active) == 1 and active[0]["entity"]["name"] == "Another Designer"
    ended = [r for r in designers if not r["active"]][0]
    assert ended["ended_at"] is not None


def test_uncapped_role_allows_several(jay):
    job = new_job(jay)
    for n in ("A", "B"):
        e = new_entity(jay, f"Helper {n}")
        jay.post(f"/api/jobs/{job['id']}/roles", json={"entity_id": e["id"], "role": "other"})
    detail = jay.get(f"/api/jobs/{job['id']}").json()
    assert len([r for r in detail["roles"] if r["role"] == "other" and r["active"]]) == 2


def test_last_person_cannot_be_removed(jay):
    job = new_job(jay)
    role_id = job["roles"][0]["id"]
    assert jay.delete(f"/api/jobs/{job['id']}/roles/{role_id}").status_code == 422


def test_hold_needs_a_future_date_and_creates_a_check_in(jay):
    job = new_job(jay)
    assert jay.post(f"/api/jobs/{job['id']}/hold", json={"until": "2000-01-01", "reason": "spring"}).status_code == 422
    r = jay.post(f"/api/jobs/{job['id']}/hold", json={"until": "2031-03-01", "reason": "Not starting till spring"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "on_hold"
    check_in = [t for t in d["tasks"] if t["title"].startswith("Check in")][0]
    assert check_in["due_date"] == "2031-03-01" and check_in["assignee_id"] == jay.id


def test_lost_needs_a_reason_and_other_needs_a_note(jay):
    job = new_job(jay)
    assert jay.post(f"/api/jobs/{job['id']}/lose", json={"reason": "other"}).status_code == 422
    r = jay.post(f"/api/jobs/{job['id']}/lose", json={"reason": "price"})
    d = r.json()
    assert d["status"] == "lost"
    assert d["open_tasks"] == 0
    assert d["stuck"] is False  # lost is not stuck


def test_revive_needs_a_next_step(jay):
    job = new_job(jay)
    jay.post(f"/api/jobs/{job['id']}/lose", json={"reason": "timing"})
    assert jay.post(f"/api/jobs/{job['id']}/revive", json={"mode": "resume"}).status_code == 422
    r = jay.post(f"/api/jobs/{job['id']}/revive", json={"mode": "resume", "next_step": step(jay.id)})
    assert r.json()["status"] == "active" and r.json()["open_tasks"] == 1


def test_search_finds_a_job_by_a_persons_phone(jay):
    kisch = new_entity(jay, "Pinches Kisch", "845-555-0102")
    new_job(jay, name="21 Mountain Rd", people=[{"entity_id": kisch["id"], "role": "owner"}])
    r = jay.get("/api/jobs", params={"q": "5550102"})
    assert [j["name"] for j in r.json()] == ["21 Mountain Rd"]
    r = jay.get("/api/jobs", params={"q": "kisch"})
    assert [j["name"] for j in r.json()] == ["21 Mountain Rd"]


def test_change_rep_moves_ownership(boss, jay):
    moshe = make_user(boss, "moshe@hstile.com", "Moshe", "rep", "Brooklyn", "Brooklyn Showroom")
    job = new_job(jay)
    d = jay.post(f"/api/jobs/{job['id']}/rep", json={"rep_id": moshe.id}).json()
    assert d["rep_id"] == moshe.id and d["owner_id"] == moshe.id
