"""Item sync against a stand-in NetSuite: what lands in the items table, and what the Team screen sees."""

from app.netsuite import NetSuiteError
from app.services import item_sync


class FakeNetSuite:
    """Answers by_id like SuiteQL would, two rows per page, and records the queries."""

    def __init__(self, rows, fail=None):
        self.rows = rows
        self.fail = fail
        self.queries = []

    def by_id(self, sql_for_after, id_field="id"):
        after = 0
        while True:
            sql = sql_for_after(after)
            if "unitstypeuom" in sql:
                if after == 0:
                    yield [{"id": "1", "abbr": "SF", "name": "Square Foot"}, {"id": "2", "abbr": "PC", "name": "Piece"}]
                return
            self.queries.append(sql)
            if self.fail:
                raise NetSuiteError(self.fail)
            page = [r for r in self.rows if int(r["id"]) > after][:2]
            if not page:
                return
            yield page
            after = int(page[-1]["id"])


def ns(i, code, display="", inactive="F", lot="F", stock="T", unit="1"):
    return {"id": str(i), "itemid": code, "displayname": display, "isinactive": inactive, "islotitem": lot,
            "custitem4": stock, "stockunit": unit}


def _engine():
    from app.db import engine

    return engine


def test_full_sync_fills_items_and_search_finds_them(client, jay):
    fake = FakeNetSuite([ns(11, "CAL-1224", "Calacatta Gold 12x24", lot="T"), ns(12, "CAR-1224"), ns(13, "OLD-1", "Old tile", inactive="T")])
    result = item_sync.run(_engine(), fake)
    assert result == {"status": "ok", "mode": "full", "rows": 3, "retired": 0}
    assert len(fake.queries) == 2  # paged by id, not by offset
    found = jay.get("/api/items", params={"q": "calacatta"}).json()
    assert found[0]["netsuite_id"] == 11 and found[0]["sku"] == "CAL-1224" and found[0]["is_lot"] is True
    assert jay.get("/api/items", params={"q": "CAR-1224"}).json()[0]["name"] == "CAR-1224"
    assert jay.get("/api/items", params={"q": "old"}).json() == []  # inactive in NetSuite
    assert jay.get("/api/items/resolve", params={"code": "https://x/item/11"}).json()["found"] is True


def test_second_run_only_asks_for_changes(client):
    item_sync.run(_engine(), FakeNetSuite([ns(1, "A")]))
    fake = FakeNetSuite([ns(1, "A", "A renamed")])
    assert item_sync.run(_engine(), fake)["mode"] == "changes"
    assert "lastmodifieddate" in fake.queries[0]


def test_full_run_retires_items_gone_from_netsuite(client, jay):
    item_sync.run(_engine(), FakeNetSuite([ns(1, "KEEP"), ns(2, "GONE")]))
    result = item_sync.run(_engine(), FakeNetSuite([ns(1, "KEEP")]), mode="full")
    assert result["retired"] == 1
    assert [i["netsuite_id"] for i in jay.get("/api/items").json()] == [1]


def test_a_failure_is_recorded_not_raised(client, boss):
    result = item_sync.run(_engine(), FakeNetSuite([], fail="NetSuite refused the keys."))
    assert result["status"] == "failed"
    status = boss.get("/api/sync/items").json()
    assert status["runs"][0]["status"] == "failed" and "refused" in status["runs"][0]["error"]


def test_only_admins_see_sync_and_button_needs_keys(client, boss, jay):
    assert jay.get("/api/sync/items").status_code == 403
    assert boss.get("/api/sync/items").json()["configured"] is False
    assert boss.post("/api/sync/items").status_code == 409


def test_only_stocking_items_show_in_search_and_units_come_along(client, jay):
    item_sync.run(_engine(), FakeNetSuite([ns(1, "REAL-1", "Real Tile"), ns(2, "ONEOFF-1", "Real Tile one-off", stock="F"), ns(3, "TRIM-1", "Real Tile trim", unit="2")]))
    found = jay.get("/api/items", params={"q": "real tile"}).json()
    assert sorted(i["netsuite_id"] for i in found) == [1, 3]
    assert {i["netsuite_id"]: i["unit"] for i in found} == {1: "SF", 3: "PC"}
    # A one-off still resolves from a scan, so an old job keeps its name; it just isn't offered.
    assert jay.get("/api/items/resolve", params={"code": "2"}).json()["found"] is True


def test_row_mapping():
    assert item_sync.to_item(ns(5, "SKU-5", "Nice Tile"), {1: "SF"}) == {
        "netsuite_id": 5, "name": "Nice Tile", "sku": "SKU-5", "active": True, "is_lot": False,
        "is_stock": True, "unit_id": 1, "unit": "SF",
    }
    assert item_sync.to_item({"id": "6", "itemid": None, "displayname": None})["name"] == "Item #6"
