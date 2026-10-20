"""After the estimate: the order's stages, the closing checklist, changes, and closing the job."""

from decimal import Decimal

import pytest

from conftest import new_job, step
from app.routers import estimates as R


@pytest.fixture()
def order(client, jay, office, monkeypatch):
    from app.db import SessionLocal
    from app.models import Item

    db = SessionLocal()
    db.add(Item(netsuite_id=10846, name="ABK Sensi", is_stock=True, unit="SqFt"))
    db.commit()
    db.close()
    monkeypatch.setattr(R, "_base_price", lambda item_id: Decimal("7.50"))
    job = new_job(jay)
    kitchen = jay.post(f"/api/jobs/{job['id']}/areas", json={"name": "Kitchen"}).json()
    jay.put(f"/api/areas/{kitchen['id']}/footage", json={"footage": 100, "source": "takeoff", "confidence": "confirmed"})
    jay.post(f"/api/jobs/{job['id']}/candidates", json={"source": "stock", "netsuite_item_id": 10846, "area_ids": [kitchen["id"]]})
    tag = jay.get(f"/api/jobs/{job['id']}").json()["candidates"][0]["tags"][0]
    jay.patch(f"/api/tags/{tag['id']}", json={"status": "chosen"})
    est = jay.post(f"/api/jobs/{job['id']}/estimates", json={"area_ids": [kitchen["id"]]}).json()
    o = jay.post(f"/api/estimates/{est['id']}/sent-by-hand", json={"netsuite_ref": "EST-2201"}).json()
    return {"job": job, "kitchen": kitchen, "est": est, "order": o}


def test_sent_by_hand_makes_an_order_and_orders_the_area(jay, order):
    assert order["order"]["stage"] == "negotiating" and order["order"]["netsuite_estimate_ref"] == "EST-2201"
    areas = {a["id"]: a for a in jay.get(f"/api/jobs/{order['job']['id']}").json()["areas"]}
    assert areas[order["kitchen"]["id"]]["status"] == "ordered"
    assert jay.post(f"/api/estimates/{order['est']['id']}/sent-by-hand", json={}).status_code == 409
    # The area moves with the order now.
    assert jay.patch(f"/api/areas/{order['kitchen']['id']}", json={"status": "open"}).status_code == 409


def test_the_whole_way_to_a_closed_job(jay, office, order):
    oid, jid = order["order"]["id"], order["job"]["id"]
    assert jay.post(f"/api/orders/{oid}/ready").status_code == 409  # not approved yet
    o = jay.post(f"/api/orders/{oid}/approve", json={"handler_id": office.id, "netsuite_order_ref": "SO-881"}).json()
    assert o["stage"] == "processing" and o["handler_id"] == office.id
    assert office.post(f"/api/orders/{oid}/ready").json()["stage"] == "delivery"
    o = office.post(f"/api/orders/{oid}/check", json={"check": "delivered"}).json()
    assert o["stage"] == "closing"
    r = office.post(f"/api/orders/{oid}/close")
    assert r.status_code == 422 and "returns" in r.json()["detail"].lower()
    for c in ("returns", "credits", "paid"):
        office.post(f"/api/orders/{oid}/check", json={"check": c})
    assert office.post(f"/api/orders/{oid}/close").json()["stage"] == "closed"
    areas = jay.get(f"/api/jobs/{jid}").json()["areas"]
    assert areas[0]["status"] == "delivered"
    detail = jay.post(f"/api/jobs/{jid}/close").json()
    assert detail["status"] == "closed" and detail["open_tasks"] == 0
    assert detail["progress"]["done"] == 8
    story = [e["summary"] for e in jay.get(f"/api/jobs/{jid}/timeline").json()]
    assert "Order approved — sales order made" in story and "Order closed" in story and any(s and s.startswith("Job closed") for s in story)


def test_an_area_on_hold_keeps_the_job_open(jay, office, order):
    jid = order["job"]["id"]
    jay.post(f"/api/jobs/{jid}/areas", json={"name": "Basement"})
    base = [a for a in jay.get(f"/api/jobs/{jid}").json()["areas"] if a["name"] == "Basement"][0]
    jay.patch(f"/api/areas/{base['id']}", json={"status": "on_hold", "hold_until": "2031-01-01", "hold_reason": "Next year"})
    oid = order["order"]["id"]
    jay.post(f"/api/orders/{oid}/approve", json={"handler_id": office.id})
    for c in ("delivered", "returns", "credits", "paid"):
        office.post(f"/api/orders/{oid}/check", json={"check": c})
    office.post(f"/api/orders/{oid}/close")
    r = jay.post(f"/api/jobs/{jid}/close")
    assert r.status_code == 422 and "Basement" in r.json()["detail"]


def test_quantity_change_after_the_order_is_recorded(jay, order):
    o = order["order"]
    line = o["lines"][0]
    assert jay.post(f"/api/orders/{o['id']}/quantity", json={"line_id": line["id"], "quantity": 120}).status_code == 422
    o2 = jay.post(f"/api/orders/{o['id']}/quantity", json={"line_id": line["id"], "quantity": 120, "reason": "Added the pantry floor"}).json()
    assert o2["lines"][0]["quantity"] == 120.0 and o2["changes"][0]["old_quantity"] == 100.0 and o2["total"] == 900.0


def test_after_the_sale_problems_go_to_the_handler(jay, office, boss, order):
    from conftest import make_user

    moshe = make_user(boss, "moshe@hstile.com", "Moshe", "back_office")
    oid, jid = order["order"]["id"], order["job"]["id"]
    jay.post(f"/api/orders/{oid}/approve", json={"handler_id": office.id})
    from app.db import SessionLocal
    from app.models import Task

    t = jay.post(f"/api/jobs/{jid}/tasks", json=step(moshe.id, "Book the truck")).json()
    db = SessionLocal()
    db.get(Task, t["id"]).order_id = oid
    db.commit()
    db.close()
    moshe.post(f"/api/tasks/{t['id']}/complete", json={"outcome": "bad_answer", "note": "No truck till Monday", "next_step": step(office.id, "Tell the customer")})
    assert [w["title"] for w in office.get("/api/dashboard/rep").json()["went_wrong"]] == ["Book the truck"]
    assert jay.get("/api/dashboard/rep").json()["went_wrong"] == []


def test_a_removed_tile_is_hidden_not_deleted(jay, order):
    jid = order["job"]["id"]
    jay.post(f"/api/jobs/{jid}/candidates", json={"source": "local", "name": "Oops"})
    oops = [c for c in jay.get(f"/api/jobs/{jid}").json()["candidates"] if c["name"] == "Oops"][0]
    jay.delete(f"/api/candidates/{oops['id']}")
    assert "Oops" not in [c["name"] for c in jay.get(f"/api/jobs/{jid}").json()["candidates"]]
    from app.db import SessionLocal
    from app.models import Candidate

    db = SessionLocal()
    assert db.get(Candidate, oops["id"]).removed_at is not None
    db.close()
