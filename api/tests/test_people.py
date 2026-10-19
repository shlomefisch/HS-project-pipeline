from conftest import make_user, new_entity, new_job, sign_in


def test_new_accounts_wait_for_an_admin(client):
    pending = sign_in(client, "newhire@hstile.com", "New Hire")
    assert pending.user["role"] == "pending"
    assert pending.get("/api/jobs").status_code == 403
    assert pending.get("/api/auth/me").status_code == 200


def test_only_the_company_domain_can_sign_in(client):
    r = client.post("/api/auth/dev", json={"email": "someone@gmail.com"})
    assert r.status_code == 403


def test_bootstrap_admin_is_admin(boss):
    assert boss.user["is_admin"] is True


def test_view_only_users_can_look_but_not_touch(boss, jay):
    viewer = make_user(boss, "viewer@hstile.com", "Viewer", "viewer")
    new_job(jay)
    assert viewer.get("/api/jobs").status_code == 200
    r = viewer.post("/api/entities", json={"name": "X", "confirm_new": True})
    assert r.status_code == 403


def test_same_phone_in_another_format_is_caught(jay):
    new_entity(jay, "Pinches Kisch", "845-555-0102")
    r = jay.post("/api/entities", json={"name": "P. Kisch", "phone": "(845) 555 0102"})
    assert r.status_code == 409
    matches = r.json()["detail"]["matches"]
    assert matches[0]["entity"]["name"] == "Pinches Kisch"
    assert "same phone" in matches[0]["reasons"]


def test_spelling_variants_are_caught(jay):
    new_entity(jay, "Pinches Kisch")
    r = jay.post("/api/entities/check", json={"name": "Pinchas Kish"})
    names = [m["entity"]["name"] for m in r.json()["matches"]]
    assert "Pinches Kisch" in names


def test_extra_spaces_are_the_same_name(jay):
    new_entity(jay, "Pinches Kisch")
    r = jay.post("/api/entities", json={"name": "  pinches   KISCH "})
    assert r.status_code == 409
    assert "same name" in r.json()["detail"]["matches"][0]["reasons"]


def test_short_company_name_finds_the_full_one(jay):
    new_entity(jay, "AtoZ Construction", kind="company")
    r = jay.post("/api/entities/check", json={"name": "AtoZ"})
    assert [m["entity"]["name"] for m in r.json()["matches"]] == ["AtoZ Construction"]


def test_unrelated_names_do_not_match(jay):
    new_entity(jay, "Pinches Kisch")
    r = jay.post("/api/entities/check", json={"name": "Rifky Freund"})
    assert r.json()["matches"] == []


def test_create_new_only_after_matches_were_declined(jay):
    new_entity(jay, "Rifky Freund", "845-555-0101")
    r = jay.post("/api/entities", json={"name": "Rifky Freund", "confirm_new": True})
    assert r.status_code == 201


def test_entity_page_shows_every_job_they_are_on(jay):
    rifky = new_entity(jay, "Rifky Freund")
    for name in ("21 Mountain Rd", "8 Lake Ave"):
        new_job(jay, name=name, people=[{"entity_id": rifky["id"], "role": "designer"}])
    r = jay.get(f"/api/entities/{rifky['id']}")
    assert sorted(j["job_name"] for j in r.json()["jobs"]) == ["21 Mountain Rd", "8 Lake Ave"]


def test_merge_moves_jobs_and_keeps_the_duplicate_record(boss, jay):
    real = new_entity(jay, "Rifky Freund", "845-555-0101")
    dupe = new_entity(jay, "Rifky F", email="rifky@example.com")
    job = new_job(jay, people=[{"entity_id": dupe["id"], "role": "designer"}])
    r = boss.post(f"/api/entities/{dupe['id']}/merge-into/{real['id']}")
    assert r.status_code == 200, r.text
    assert r.json()["into"]["email"] == "rifky@example.com"
    detail = jay.get(f"/api/jobs/{job['id']}").json()
    assert detail["roles"][0]["entity"]["id"] == real["id"]
    gone = jay.get(f"/api/entities/{dupe['id']}").json()
    assert gone["entity"]["active"] is False
    assert gone["merged_into"]["id"] == real["id"]


def test_cannot_deactivate_someone_holding_live_work(boss, jay):
    new_job(jay)
    r = boss.patch(f"/api/users/{jay.id}", json={"active": False})
    assert r.status_code == 409


def test_assignee_suggestions_follow_habits(boss, jay, office):
    job = new_job(jay)
    for _ in range(3):
        jay.post(f"/api/jobs/{job['id']}/tasks", json={"title": "x", "assignee_id": office.id, "due_date": "2030-01-01"})
    r = jay.get("/api/users/assignee-suggestions")
    assert r.json()[0]["id"] == office.id


def test_merge_does_not_leave_two_active_designers(boss, jay):
    real = new_entity(jay, "Rifky Freund", "845-555-0101")
    dupe = new_entity(jay, "Rifky F.")
    job = new_job(jay, people=[{"entity_id": real["id"], "role": "designer"}])
    jay.post(f"/api/jobs/{job['id']}/roles", json={"entity_id": dupe["id"], "role": "other"})
    jay.post(f"/api/jobs/{job['id']}/roles", json={"entity_id": dupe["id"], "role": "designer"})
    # dupe is now the active designer; real was ended by the cap. Merge dupe into real.
    boss.post(f"/api/entities/{dupe['id']}/merge-into/{real['id']}")
    roles = jay.get(f"/api/jobs/{job['id']}").json()["roles"]
    active_designers = [r for r in roles if r["role"] == "designer" and r["active"]]
    assert len(active_designers) == 1 and active_designers[0]["entity"]["id"] == real["id"]


def test_blanking_a_required_field_is_refused_not_a_crash(boss, jay):
    assert boss.patch(f"/api/users/{jay.id}", json={"role": None}).status_code == 422
    e = new_entity(jay, "Someone")
    assert jay.patch(f"/api/entities/{e['id']}", json={"kind": None}).status_code == 422
    assert jay.patch(f"/api/entities/{e['id']}", json={"company_id": 99999}).status_code == 422


def test_negative_limit_is_not_a_crash(jay):
    assert jay.get("/api/entities", params={"limit": -1}).status_code == 200
