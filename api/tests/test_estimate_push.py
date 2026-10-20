"""Sending an estimate to NetSuite, against a stand-in NetSuite."""

from decimal import Decimal

import pytest

from conftest import new_entity, new_job
from app.netsuite import NetSuiteError
from app.services import estimate_push as P


class FakeQL:
    def __init__(self, existing=None, customers=()):
        self.existing, self.customers, self.sql = existing, list(customers), []

    def page(self, sql, limit=1000, offset=0):
        self.sql.append(sql)
        if "FROM transaction" in sql:
            return ([{"id": self.existing}] if self.existing else []), False
        if "FROM customer" in sql:
            return self.customers, False
        if "FROM classification" in sql:
            return [{"id": "4"}], False
        return [], False


class FakeRec:
    def __init__(self, fail=False):
        self.made, self.fail = [], fail

    def create(self, record, body):
        if self.fail and record == "estimate":
            raise NetSuiteError("Invalid field")
        self.made.append((record, body))
        return 9000 + len(self.made)


@pytest.fixture()
def ready(client, jay, monkeypatch):
    from app.config import settings
    from app.db import SessionLocal
    from app.models import Item
    from app.routers import estimates as R

    object.__setattr__(settings, "ns_account", "5032967")
    object.__setattr__(settings, "ns_consumer_key", "ck")
    object.__setattr__(settings, "ns_write_token_id", "wt")
    object.__setattr__(settings, "ns_write_token_secret", "ws")
    db = SessionLocal()
    db.add(Item(netsuite_id=10846, name="ABK Sensi", is_stock=True, unit="SqFt"))
    db.commit()
    db.close()
    monkeypatch.setattr(R, "_base_price", lambda item_id: Decimal("7.50"))
    owner = new_entity(jay, "Pinches Kisch", "845-555-0102")
    job = new_job(jay, people=[{"entity_id": owner["id"], "role": "owner"}])
    area = jay.post(f"/api/jobs/{job['id']}/areas", json={"name": "Kitchen"}).json()
    jay.put(f"/api/areas/{area['id']}/footage", json={"footage": 100, "source": "takeoff", "confidence": "confirmed"})
    jay.post(f"/api/jobs/{job['id']}/candidates", json={"source": "stock", "netsuite_item_id": 10846, "area_ids": [area["id"]]})
    tag = jay.get(f"/api/jobs/{job['id']}").json()["candidates"][0]["tags"][0]
    jay.patch(f"/api/tags/{tag['id']}", json={"status": "chosen"})
    est = jay.post(f"/api/jobs/{job['id']}/estimates", json={"area_ids": [area["id"]]}).json()
    yield {"job": job, "owner": owner, "est": est}
    for key in ("ns_account", "ns_consumer_key", "ns_write_token_id", "ns_write_token_secret"):
        object.__setattr__(settings, key, "")


def test_owner_first_and_warnings_must_be_read(jay, ready, monkeypatch):
    chk = jay.get(f"/api/estimates/{ready['est']['id']}/push").json()
    assert chk["configured"] and chk["bill_to"][0]["role"] == "owner" and chk["blockers"] == []
    assert any("availability" in w for w in chk["warnings"])
    monkeypatch.setattr(P, "write_client", lambda: (FakeRec(), FakeQL()))
    r = jay.post(f"/api/estimates/{ready['est']['id']}/push", json={"entity_id": ready["owner"]["id"], "netsuite_customer_id": 55})
    assert r.status_code == 409


def test_push_makes_an_estimate_with_our_prices_and_remembers_the_customer(jay, ready, monkeypatch):
    rec, ql = FakeRec(), FakeQL()
    monkeypatch.setattr(P, "write_client", lambda: (rec, ql))
    r = jay.post(f"/api/estimates/{ready['est']['id']}/push",
                 json={"entity_id": ready["owner"]["id"], "netsuite_customer_id": 55, "acknowledge_warnings": True})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pushed" and r.json()["netsuite_estimate_id"] == 9001
    record, body = rec.made[0]
    assert record == "estimate" and body["entity"] == {"id": "55"} and body["class"] == {"id": "4"}
    line = body["item"]["items"][0]
    assert line["item"] == {"id": "10846"} and line["rate"] == 7.5 and line["quantity"] == 100.0 and line["price"] == {"id": "-1"}
    assert body["externalId"] == f"pipeline-est-{ready['est']['id']}"
    assert jay.get(f"/api/entities/{ready['owner']['id']}").json()["entity"]["netsuite_customer_id"] == "55"
    story = [e["summary"] for e in jay.get(f"/api/jobs/{ready['job']['id']}/timeline").json()]
    assert "Order placed — estimate sent to NetSuite" in story


def test_already_there_is_not_made_twice(jay, ready, monkeypatch):
    rec = FakeRec()
    monkeypatch.setattr(P, "write_client", lambda: (rec, FakeQL(existing="7777")))
    r = jay.post(f"/api/estimates/{ready['est']['id']}/push",
                 json={"entity_id": ready["owner"]["id"], "netsuite_customer_id": 55, "acknowledge_warnings": True})
    assert r.json()["netsuite_estimate_id"] == 7777 and rec.made == []


def test_a_new_customer_only_when_asked_and_kept_if_the_estimate_fails(jay, ready, monkeypatch):
    rec = FakeRec(fail=True)
    monkeypatch.setattr(P, "write_client", lambda: (rec, FakeQL()))
    body = {"entity_id": ready["owner"]["id"], "acknowledge_warnings": True}
    assert jay.post(f"/api/estimates/{ready['est']['id']}/push", json=body).status_code == 422
    r = jay.post(f"/api/estimates/{ready['est']['id']}/push", json={**body, "create_customer": True})
    assert r.status_code == 502
    assert rec.made[0][0] == "customer" and rec.made[0][1]["firstName"] == "Pinches"
    assert jay.get(f"/api/entities/{ready['owner']['id']}").json()["entity"]["netsuite_customer_id"] == "9001"
    assert jay.get(f"/api/jobs/{ready['job']['id']}/estimates").json()[0]["status"] == "draft"


def test_customer_matches_say_why():
    class E:
        name, email, phone, kind = "Pinches Kisch", "pk@x.com", "845-555-0102", "person"

    ql = FakeQL(customers=[{"id": "12", "entityid": "Kisch, Pinches", "companyname": None, "email": "pk@x.com", "phone": "(845) 555-0102"}])
    m = P.find_customers(ql, E())
    assert m[0]["id"] == 12 and "same email" in m[0]["why"] and "same phone" in m[0]["why"]
    assert "'" not in P._q("O'Brien'; DROP")
