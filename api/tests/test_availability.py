"""Availability: one lot covers it, two lots is short until the rep says so, short tells the rep."""

import pytest

from conftest import new_job
from app.routers import selection


def _stock(*lots):
    rows = [{"location": "NJ", "lot": lot, "on_hand": q, "available": q} for lot, q in lots]
    return {"by_lot": True, "rows": rows, "totals": {"available": sum(q for _, q in lots), "on_hand": sum(q for _, q in lots)}}


@pytest.fixture()
def tile(client, jay, monkeypatch):
    """A job with a Kitchen of 420 sf and a chosen stock tile in it."""
    from app.db import SessionLocal
    from app.models import Item

    db = SessionLocal()
    db.add(Item(netsuite_id=10846, name="ABK Sensi White 24x48", sku="ABK.SN", is_stock=True, unit="SqFt"))
    db.add(Item(netsuite_id=20001, name="Bullnose trim", is_stock=True, unit="PC"))
    db.commit()
    db.close()
    job = new_job(jay)
    area = jay.post(f"/api/jobs/{job['id']}/areas", json={"name": "Kitchen"}).json()
    jay.put(f"/api/areas/{area['id']}/footage", json={"footage": 420, "source": "designer", "by": "Rifky", "confidence": "approximate"})
    jay.post(f"/api/jobs/{job['id']}/candidates", json={"source": "stock", "netsuite_item_id": 10846, "area_ids": [area["id"]]})
    tag = jay.get(f"/api/jobs/{job['id']}").json()["candidates"][0]["tags"][0]
    jay.patch(f"/api/tags/{tag['id']}", json={"status": "chosen"})
    return {"job": job, "area": area, "tag": tag, "set": lambda s: monkeypatch.setattr(selection, "_live_stock", lambda item_id: s)}


def _tasks(jay, job_id):
    return [t["title"] for t in jay.get(f"/api/jobs/{job_id}").json()["tasks"] if t["status"] == "open"]


def test_one_lot_covers_it(jay, tile):
    tile["set"](_stock(("GU6", 2151.52), ("gm6", 81.36)))
    r = jay.post(f"/api/tags/{tile['tag']['id']}/availability/check").json()
    assert r["avail_status"] == "available" and r["avail_lot"] == "GU6" and r["avail_need"] == 420.0
    story = [e["summary"] for e in jay.get(f"/api/jobs/{tile['job']['id']}/timeline").json()]
    assert any(s and s.startswith("Available: ABK Sensi White 24x48 for Kitchen in lot GU6") for s in story)


def test_enough_only_across_lots_is_short_and_the_rep_decides(jay, office, tile):
    tile["set"](_stock(("A", 300), ("B", 200)))
    r = jay.post(f"/api/tags/{tile['tag']['id']}/availability/check").json()
    assert r["avail_status"] == "two_lots"
    assert any(t.startswith("Short: ABK Sensi White 24x48 for Kitchen") for t in _tasks(jay, tile["job"]["id"]))
    # Checking again doesn't pile up tasks.
    jay.post(f"/api/tags/{tile['tag']['id']}/availability/check")
    assert sum(t.startswith("Short:") for t in _tasks(jay, tile["job"]["id"])) == 1
    # Only the rep's call, and only with a reason.
    assert office.post(f"/api/tags/{tile['tag']['id']}/availability/two-lots", json={"reason": "fine"}).status_code == 403
    assert jay.post(f"/api/tags/{tile['tag']['id']}/availability/two-lots", json={"reason": ""}).status_code == 422
    r = jay.post(f"/api/tags/{tile['tag']['id']}/availability/two-lots", json={"reason": "Two rooms, lots won't touch"})
    assert r.json()["avail_status"] == "override"


def test_not_enough_is_short(jay, tile):
    tile["set"](_stock(("A", 100)))
    assert jay.post(f"/api/tags/{tile['tag']['id']}/availability/check").json()["avail_status"] == "short"


def test_needs_a_number_and_square_feet(jay, tile):
    jay.put(f"/api/areas/{tile['area']['id']}/footage", json={"footage": None})
    tile["set"](_stock(("A", 1000)))
    r = jay.post(f"/api/tags/{tile['tag']['id']}/availability/check")
    assert r.status_code == 422 and "footage" in r.json()["detail"]
    # A quantity on the tile itself beats the area's footage.
    jay.patch(f"/api/tags/{tile['tag']['id']}", json={"quantity": 50})
    assert jay.post(f"/api/tags/{tile['tag']['id']}/availability/check").json()["avail_need"] == 50.0


def test_items_counted_in_pieces_are_not_compared(jay, tile):
    job, area = tile["job"], tile["area"]
    jay.post(f"/api/jobs/{job['id']}/candidates", json={"source": "stock", "netsuite_item_id": 20001, "area_ids": [area["id"]]})
    trim = [c for c in jay.get(f"/api/jobs/{job['id']}").json()["candidates"] if c["netsuite_item_id"] == 20001][0]["tags"][0]
    tile["set"](_stock(("A", 1000)))
    r = jay.post(f"/api/tags/{trim['id']}/availability/check")
    assert r.status_code == 422 and "PC" in r.json()["detail"]


def test_local_supplier_and_overseas_lead_time(jay, tile):
    job, area = tile["job"], tile["area"]
    jay.post(f"/api/jobs/{job['id']}/candidates", json={"source": "local", "name": "Local grey", "area_ids": [area["id"]]})
    jay.post(f"/api/jobs/{job['id']}/candidates", json={"source": "overseas", "name": "Terrazzo", "supplier": "Milano", "area_ids": [area["id"]]})
    cands = {c["name"]: c["tags"][0] for c in jay.get(f"/api/jobs/{job['id']}").json()["candidates"] if c["name"]}
    assert jay.post(f"/api/tags/{cands['Local grey']['id']}/availability/check").status_code == 422
    assert jay.post(f"/api/tags/{cands['Local grey']['id']}/availability/confirm", json={"ok": False}).status_code == 422
    r = jay.post(f"/api/tags/{cands['Local grey']['id']}/availability/confirm", json={"ok": False, "note": "Out till December"})
    assert r.json()["avail_status"] == "short"
    assert jay.post(f"/api/tags/{cands['Terrazzo']['id']}/availability/confirm", json={"ok": True}).status_code == 422
    r = jay.post(f"/api/tags/{cands['Terrazzo']['id']}/availability/confirm", json={"ok": True, "lead_time_weeks": 12})
    assert r.json()["avail_status"] == "confirmed"
    terrazzo = [c for c in jay.get(f"/api/jobs/{job['id']}").json()["candidates"] if c["name"] == "Terrazzo"][0]
    assert terrazzo["lead_time_weeks"] == 12
