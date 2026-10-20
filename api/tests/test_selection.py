from app.db import SessionLocal
from app.models import Item
from conftest import new_job


def _items():
    db = SessionLocal()
    db.merge(Item(netsuite_id=100101, name="Calacatta Gold 12x24", sku="CAL-1224", active=True))
    db.commit()
    db.close()


def _areas(jay, job_id, *names):
    return [jay.post(f"/api/jobs/{job_id}/areas", json={"name": n}).json() for n in names]


def test_scan_resolves_a_url_to_the_item(jay):
    _items()
    r = jay.get("/api/items/resolve", params={"code": "https://5032967.app.netsuite.com/app/x/100101"})
    assert r.json()["found"] is True and r.json()["item"]["name"] == "Calacatta Gold 12x24"


def test_unknown_scan_still_returns_the_id(jay):
    r = jay.get("/api/items/resolve", params={"code": "https://x/999999"})
    assert r.json() == {"netsuite_id": 999999, "found": False, "item": None}


def test_stock_tile_needs_an_item_and_local_needs_a_name(jay):
    job = new_job(jay)
    assert jay.post(f"/api/jobs/{job['id']}/candidates", json={"source": "stock"}).status_code == 422
    assert jay.post(f"/api/jobs/{job['id']}/candidates", json={"source": "local"}).status_code == 422


def test_a_scan_of_an_item_not_synced_yet_is_kept(jay):
    job = new_job(jay)
    r = jay.post(f"/api/jobs/{job['id']}/candidates", json={"source": "stock", "netsuite_item_id": 555555})
    assert r.status_code == 201
    cand = jay.get(f"/api/jobs/{job['id']}").json()["candidates"][0]
    assert cand["display_name"] == "Item #555555 (details pending)"


def test_same_tile_chosen_for_one_area_and_declined_for_another(jay):
    _items()
    job = new_job(jay)
    kitchen, vestibule = _areas(jay, job["id"], "Kitchen", "Vestibule")
    jay.post(
        f"/api/jobs/{job['id']}/candidates",
        json={"source": "stock", "netsuite_item_id": 100101, "area_ids": [kitchen["id"], vestibule["id"]]},
    )
    tags = jay.get(f"/api/jobs/{job['id']}").json()["candidates"][0]["tags"]
    assert len(tags) == 2  # one tile, two lines
    by_area = {t["area_id"]: t for t in tags}
    assert jay.patch(f"/api/tags/{by_area[kitchen['id']]['id']}", json={"status": "chosen"}).status_code == 200
    assert jay.patch(f"/api/tags/{by_area[vestibule['id']]['id']}", json={"status": "declined"}).status_code == 422
    r = jay.patch(f"/api/tags/{by_area[vestibule['id']]['id']}", json={"status": "declined", "reason": "Too busy"})
    assert r.json()["status"] == "declined"
    statuses = {t["area_id"]: t["status"] for t in jay.get(f"/api/jobs/{job['id']}").json()["candidates"][0]["tags"]}
    assert statuses == {kitchen["id"]: "chosen", vestibule["id"]: "declined"}


def test_declined_can_be_uncrossed_but_never_removed(jay):
    job = new_job(jay)
    (kitchen,) = _areas(jay, job["id"], "Kitchen")
    jay.post(f"/api/jobs/{job['id']}/candidates", json={"source": "local", "name": "Grey 24x24", "area_ids": [kitchen["id"]]})
    tag = jay.get(f"/api/jobs/{job['id']}").json()["candidates"][0]["tags"][0]
    jay.patch(f"/api/tags/{tag['id']}", json={"status": "declined", "reason": "Too cold"})
    assert jay.delete(f"/api/tags/{tag['id']}").status_code == 409
    r = jay.patch(f"/api/tags/{tag['id']}", json={"status": "considering"})
    assert r.json()["status"] == "considering" and r.json()["reason"] is None
    story = " | ".join(e["summary"] or "" for e in jay.get(f"/api/jobs/{job['id']}/timeline").json())
    assert "Tile declined — Too cold" in story and "Decision undone" in story


def test_area_decided_needs_a_chosen_tile(jay):
    job = new_job(jay)
    (kitchen,) = _areas(jay, job["id"], "Kitchen")
    assert jay.patch(f"/api/areas/{kitchen['id']}", json={"status": "decided"}).status_code == 422


def test_area_on_hold_needs_a_date_and_a_reason(jay):
    job = new_job(jay)
    (basement,) = _areas(jay, job["id"], "Basement")
    assert jay.patch(f"/api/areas/{basement['id']}", json={"status": "on_hold"}).status_code == 422
    r = jay.patch(f"/api/areas/{basement['id']}", json={"status": "on_hold", "hold_until": "2031-04-01", "hold_reason": "Next year"})
    assert r.json()["status"] == "on_hold"


def test_area_names_are_unique_per_job_ignoring_case(jay):
    job = new_job(jay)
    a = jay.post(f"/api/jobs/{job['id']}/areas", json={"name": "Kitchen"}).json()
    b = jay.post(f"/api/jobs/{job['id']}/areas", json={"name": "KITCHEN"}).json()
    assert a["id"] == b["id"]


def test_overseas_without_lead_time_is_flagged(jay):
    job = new_job(jay)
    jay.post(f"/api/jobs/{job['id']}/candidates", json={"source": "overseas", "name": "Terrazzo Verde"})
    assert jay.get(f"/api/jobs/{job['id']}").json()["candidates"][0]["needs_lead_time"] is True


def test_sample_marked_sent_gets_todays_date(jay):
    job = new_job(jay)
    s = jay.post(f"/api/jobs/{job['id']}/samples", json={"description": "Calacatta + Carrara"}).json()
    r = jay.patch(f"/api/samples/{s['id']}", json={"status": "sent"})
    assert r.json()["sent_on"] is not None


def test_a_tile_added_by_mistake_can_be_removed_until_decided(jay):
    job = new_job(jay)
    (kitchen,) = _areas(jay, job["id"], "Kitchen")
    jay.post(f"/api/jobs/{job['id']}/candidates", json={"source": "local", "name": "Oops tile"})
    jay.post(f"/api/jobs/{job['id']}/candidates", json={"source": "local", "name": "Kept tile", "area_ids": [kitchen["id"]]})
    cands = {c["name"]: c for c in jay.get(f"/api/jobs/{job['id']}").json()["candidates"]}
    assert jay.delete(f"/api/candidates/{cands['Oops tile']['id']}").status_code == 200
    jay.patch(f"/api/tags/{cands['Kept tile']['tags'][0]['id']}", json={"status": "chosen"})
    assert jay.delete(f"/api/candidates/{cands['Kept tile']['id']}").status_code == 409
    names = [c["name"] for c in jay.get(f"/api/jobs/{job['id']}").json()["candidates"]]
    assert names == ["Kept tile"]
    story = [e["summary"] for e in jay.get(f"/api/jobs/{job['id']}/timeline").json()]
    assert "Tile removed (added by mistake): Oops tile" in story
