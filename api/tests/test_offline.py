"""A save sent again with the same one-time key is done once."""

from conftest import new_job, step


def test_a_repeat_with_the_same_key_is_not_done_twice(jay):
    job = new_job(jay)
    h = {"Idempotency-Key": "k-1234567890abcdef-0001"}
    body = {"kind": "contact", "summary": "Called Rifky", "next_step": step(jay.id, "Send samples")}
    first = jay.client.post(f"/api/jobs/{job['id']}/events", json=body, headers={**jay._h(), **h})
    # The phone lost signal before the answer came back, so it sends again.
    again = jay.client.post(f"/api/jobs/{job['id']}/events", json=body, headers={**jay._h(), **h})
    assert first.status_code == again.status_code == 201
    assert again.headers.get("idempotent-replay") == "true"
    titles = [t["title"] for t in jay.get(f"/api/jobs/{job['id']}").json()["tasks"]]
    assert titles.count("Send samples") == 1


def test_a_refusal_is_remembered_too(jay):
    job = new_job(jay)
    h = {**jay._h(), "Idempotency-Key": "k-1234567890abcdef-0002"}
    body = {"kind": "contact", "summary": "No next step"}
    assert jay.client.post(f"/api/jobs/{job['id']}/events", json=body, headers=h).status_code == 422
    assert jay.client.post(f"/api/jobs/{job['id']}/events", json=body, headers=h).status_code == 422


def test_without_a_key_nothing_changes(jay):
    job = new_job(jay)
    body = {"kind": "contact", "summary": "Twice on purpose", "next_step": step(jay.id, "A")}
    jay.post(f"/api/jobs/{job['id']}/events", json=body)
    jay.post(f"/api/jobs/{job['id']}/events", json=body)
    story = [e["summary"] for e in jay.get(f"/api/jobs/{job['id']}/timeline").json()]
    assert story.count("Twice on purpose") == 2


def test_a_save_refused_for_sign_in_goes_through_after_signing_in(jay):
    job = new_job(jay)
    key = {"Idempotency-Key": "k-1234567890abcdef-0003"}
    body = {"kind": "contact", "summary": "Sent after sign-in", "next_step": step(jay.id, "B")}
    assert jay.client.post(f"/api/jobs/{job['id']}/events", json=body, headers=key).status_code == 401  # no session
    r = jay.client.post(f"/api/jobs/{job['id']}/events", json=body, headers={**jay._h(), **key})
    assert r.status_code == 201 and r.headers.get("idempotent-replay") is None
