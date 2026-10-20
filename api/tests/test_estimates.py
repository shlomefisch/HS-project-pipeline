"""Estimates: footage is a hard gate, Base Price by default, the rep can change any price."""

from decimal import Decimal

import pytest

from conftest import new_job
from app.routers import estimates as R


@pytest.fixture()
def job(client, jay, monkeypatch):
    from app.db import SessionLocal
    from app.models import Item

    db = SessionLocal()
    db.add(Item(netsuite_id=10846, name="ABK Sensi White 24x48", is_stock=True, unit="SqFt"))
    db.add(Item(netsuite_id=20001, name="Bullnose trim", is_stock=True, unit="PC"))
    db.commit()
    db.close()
    prices = {10846: Decimal("7.50"), 20001: Decimal("12.00")}
    monkeypatch.setattr(R, "_base_price", lambda item_id: prices.get(item_id))
    j = new_job(jay)
    kitchen = jay.post(f"/api/jobs/{j['id']}/areas", json={"name": "Kitchen"}).json()
    mud = jay.post(f"/api/jobs/{j['id']}/areas", json={"name": "Mudroom"}).json()
    for item_id, area in ((10846, kitchen), (20001, kitchen), (10846, mud)):
        jay.post(f"/api/jobs/{j['id']}/candidates", json={"source": "stock", "netsuite_item_id": item_id, "area_ids": [area["id"]]})
    for c in jay.get(f"/api/jobs/{j['id']}").json()["candidates"]:
        for t in c["tags"]:
            jay.patch(f"/api/tags/{t['id']}", json={"status": "chosen"})
    return {"id": j["id"], "kitchen": kitchen, "mud": mud}


def _footage(jay, area, n, confidence="confirmed"):
    jay.put(f"/api/areas/{area['id']}/footage", json={"footage": n, "source": "takeoff", "confidence": confidence})


def test_no_footage_no_estimate(jay, job):
    r = jay.post(f"/api/jobs/{job['id']}/estimates", json={"area_ids": [job["kitchen"]["id"], job["mud"]["id"]]})
    assert r.status_code == 422 and "Kitchen" in r.json()["detail"] and "Mudroom" in r.json()["detail"]


def test_lines_priced_from_base_price_and_pieces_dont_borrow_footage(jay, job):
    _footage(jay, job["kitchen"], 420, "approximate")
    est = jay.post(f"/api/jobs/{job['id']}/estimates", json={"area_ids": [job["kitchen"]["id"]]}).json()
    lines = {ln["description"]: ln for ln in est["lines"]}
    tile = lines["ABK Sensi White 24x48 — Kitchen"]
    assert tile["quantity"] == 420.0 and tile["price"] == 7.5 and tile["base_price"] == 7.5 and tile["amount"] == 3150.0
    trim = lines["Bullnose trim — Kitchen"]
    assert trim["unit"] == "PC" and trim["quantity"] is None  # pieces, not the kitchen's square feet
    text = " ".join(est["warnings"])
    assert "approximate footage" in text and "no quantity" in text and "not checked" in text
    assert jay.post(f"/api/jobs/{job['id']}/estimates", json={"area_ids": [job["kitchen"]["id"]]}).status_code == 409


def test_rep_changes_a_price_and_can_go_back_to_base(jay, job):
    _footage(jay, job["kitchen"], 100)
    est = jay.post(f"/api/jobs/{job['id']}/estimates", json={"area_ids": [job["kitchen"]["id"]]}).json()
    tile = [ln for ln in est["lines"] if ln["unit"] == "SqFt"][0]
    est = jay.patch(f"/api/estimate-lines/{tile['id']}", json={"price": 6.25, "price_note": "Contractor deal"}).json()
    tile = [ln for ln in est["lines"] if ln["id"] == tile["id"]][0]
    assert tile["price"] == 6.25 and tile["overridden"] and tile["base_price"] == 7.5
    story = [e["summary"] for e in jay.get(f"/api/jobs/{job['id']}/timeline").json()]
    assert any(s and s.startswith("Price changed on ABK Sensi White 24x48 — Kitchen: 6.25 (Base Price 7.50)") for s in story)
    est = jay.patch(f"/api/estimate-lines/{tile['id']}", json={"price": None}).json()
    assert [ln for ln in est["lines"] if ln["id"] == tile["id"]][0]["price"] == 7.5


def test_on_hold_areas_wait_for_their_own_order(jay, job):
    _footage(jay, job["mud"], 80)
    jay.patch(f"/api/areas/{job['mud']['id']}", json={"status": "on_hold", "hold_until": "2031-01-01", "hold_reason": "Next year"})
    r = jay.post(f"/api/jobs/{job['id']}/estimates", json={"area_ids": [job["mud"]["id"]]})
    assert r.status_code == 422 and "own order" in r.json()["detail"]


def test_discard_frees_the_job_for_a_new_one(jay, job):
    _footage(jay, job["kitchen"], 100)
    est = jay.post(f"/api/jobs/{job['id']}/estimates", json={"area_ids": [job["kitchen"]["id"]]}).json()
    assert jay.post(f"/api/estimates/{est['id']}/discard").status_code == 200
    assert jay.post(f"/api/jobs/{job['id']}/estimates", json={"area_ids": [job["kitchen"]["id"]]}).status_code == 201


def test_a_zero_quantity_is_refused_not_a_crash(jay, job):
    tag = jay.get(f"/api/jobs/{job['id']}").json()["candidates"][1]["tags"][0]
    assert jay.patch(f"/api/tags/{tag['id']}", json={"quantity": 0}).status_code == 422


def test_progress_fills_from_the_left(jay, job):
    p = jay.get(f"/api/jobs/{job['id']}").json()["progress"]
    assert [s["done"] for s in p["stages"]] == [True, True, False, False, False, False, False, False]  # chosen tiles, no footage yet
    assert p["current"] == "Footage"
    _footage(jay, job["kitchen"], 100)
    _footage(jay, job["mud"], 80)
    p = jay.get("/api/jobs", params={"mine": 1}).json()[0]["progress"]
    assert p["done"] == 3 and p["current"] == "Availability"
