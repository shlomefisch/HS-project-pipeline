"""Sign-in with passwords the admin hands out."""

from app.passwords import hash_password, problem_with, verify_password


def test_hash_round_trip_and_salt():
    h = hash_password("tile-floor-42")
    assert verify_password("tile-floor-42", h) and not verify_password("tile-floor-43", h)
    assert h != hash_password("tile-floor-42")
    assert not verify_password("x", None) and not verify_password("x", "garbage")


def test_password_rules():
    assert problem_with("short") and problem_with(" spaced-out ") and problem_with(None)
    assert problem_with("long-enough") is None


def _login(client, email, password):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def _add(boss, email="dina@hstile.com", password="temp-pass-1", **kw):
    body = {"email": email, "name": "Dina", "role": "back_office", "password": password, **kw}
    return boss.post("/api/users", json=body)


def test_admin_adds_a_person_who_must_pick_their_own_password(client, boss):
    r = _add(boss)
    assert r.status_code == 201 and r.json()["must_change_password"] is True
    assert "password_hash" not in r.json()
    res = _login(client, "Dina@hstile.com ", "temp-pass-1")
    assert res.status_code == 200 and res.json()["user"]["must_change_password"] is True
    h = {"Authorization": f"Bearer {res.json()['token']}"}
    assert client.post("/api/auth/password", json={"current_password": "nope", "new_password": "my-own-pass"}, headers=h).status_code == 400
    ch = client.post("/api/auth/password", json={"current_password": "temp-pass-1", "new_password": "my-own-pass"}, headers=h)
    assert ch.status_code == 200 and ch.json()["user"]["must_change_password"] is False
    # The old session ended with the change; the new one works.
    assert client.get("/api/auth/me", headers=h).status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {ch.json()['token']}"}).status_code == 200
    assert _login(client, "dina@hstile.com", "temp-pass-1").status_code == 400
    assert _login(client, "dina@hstile.com", "my-own-pass").status_code == 200


def test_wrong_password_and_unknown_email_look_the_same(client, boss):
    _add(boss)
    a, b = _login(client, "dina@hstile.com", "wrong-one"), _login(client, "nobody@hstile.com", "wrong-one")
    assert a.status_code == b.status_code == 400 and a.json() == b.json()


def test_lockout_after_repeated_misses_and_admin_reset_clears_it(client, boss):
    uid = _add(boss).json()["id"]
    for _ in range(8):
        _login(client, "dina@hstile.com", "wrong-one")
    assert _login(client, "dina@hstile.com", "temp-pass-1").status_code == 429
    assert boss.post(f"/api/users/{uid}/password", json={"password": "fresh-temp-1"}).status_code == 200
    assert _login(client, "dina@hstile.com", "fresh-temp-1").status_code == 200


def test_deactivated_people_cannot_sign_in(client, boss):
    uid = _add(boss).json()["id"]
    boss.patch(f"/api/users/{uid}", json={"active": False})
    assert _login(client, "dina@hstile.com", "temp-pass-1").status_code == 403


def test_only_admins_add_people_and_no_duplicates(client, boss, jay):
    assert _add(jay, email="x@hstile.com").status_code == 403
    assert _add(boss).status_code == 201
    assert _add(boss).status_code == 409
    assert _add(boss, email="y@hstile.com", password="short").status_code == 422


def test_first_password_needs_no_current_one(client, boss):
    r = boss.post("/api/auth/password", json={"current_password": "", "new_password": "boss-pass-1"})
    assert r.status_code == 200
    assert _login(client, "boss@hstile.com", "boss-pass-1").status_code == 200
    assert boss.post(f"/api/users/{boss.id}/password", json={"password": "other-pass"}).status_code in (401, 422)


def test_password_never_reaches_the_history(client, boss):
    from sqlalchemy import text

    from app.db import engine

    _add(boss)
    with engine.connect() as c:
        dump = " ".join(str(r[0]) for r in c.execute(text("SELECT changes FROM audit_log")))
    assert "scrypt$" not in dump and "temp-pass-1" not in dump
