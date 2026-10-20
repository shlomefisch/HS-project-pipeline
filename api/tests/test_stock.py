"""Live stock lookup, against a stand-in NetSuite."""

from app.netsuite import NetSuiteError
from app.services import stock


class Fake:
    def __init__(self, lots_ok=True):
        self.lots_ok = lots_ok
        self.sql = []

    def page(self, sql, limit=1000, offset=0):
        self.sql.append(sql)
        if "inventorynumberlocation" in sql or "inventorybalance" in sql:
            if not self.lots_ok:
                raise NetSuiteError("not allowed")
            return [
                {"location": "1", "lot": "L-204", "onhand": "200", "available": "100"},
                {"location": 1, "lot": "L-204", "onhand": "100", "available": "20"},  # second bin
                {"location": "1", "lot": "L-311", "onhand": 500, "available": 500},
                {"location": "2", "lot": "L-204", "onhand": 0, "available": 0},
            ], False
        if "FROM location" in sql:
            return [{"id": "1", "name": "Newark"}, {"id": "2", "name": "Monsey"}], False
        if "aggregateitemlocation" in sql:
            raise NetSuiteError("unsupported")
        if "inventoryitemlocations" in sql:
            return [{"location": "1", "onhand": 800, "available": 620}], False
        return [{"unit": "SF"}], False


def test_by_lot_with_totals_and_empty_rows_dropped():
    stock._working = None
    stock._locations = None
    r = stock.fetch(Fake(), 11)
    assert r["by_lot"] and r["unit"] == "SF"
    assert [x["lot"] for x in r["rows"]] == ["L-311", "L-204"]  # most free first
    assert r["totals"] == {"on_hand": 800.0, "available": 620.0}


def test_falls_back_to_locations_when_lots_are_not_readable():
    stock._working = None
    fake = Fake(lots_ok=False)
    r = stock.fetch(fake, 11)
    assert not r["by_lot"] and r["via"] == "item_locations"
    assert r["rows"] == [{"location": "Newark", "lot": None, "on_hand": 800.0, "available": 620.0}]
    # Next time it goes straight to the one that worked.
    fake.sql.clear()
    stock.fetch(fake, 11)
    assert "inventoryitemlocations" in fake.sql[0]


def test_every_error_is_reported_when_nothing_works():
    class Dead(Fake):
        def page(self, sql, limit=1000, offset=0):
            raise NetSuiteError("nope")

    stock._working = None
    try:
        stock.fetch(Dead(), 11)
        raise AssertionError("should have failed")
    except NetSuiteError as exc:
        assert "[lots]" in str(exc) and "[item_locations]" in str(exc)


def test_answers_are_cached_for_a_few_minutes():
    calls = []

    def factory():
        calls.append(1)
        return Fake()

    stock._cache.clear()
    stock.get(factory, 12)
    stock.get(factory, 12)
    stock.get(factory, 12, fresh=True)
    assert len(calls) == 2


def test_stock_needs_netsuite_connected(client, jay):
    # (Checking a one-off item is refused too, once connected — covered by the router's is_stock check.)
    assert jay.get("/api/items/11/stock").status_code == 409


def test_numbers_still_come_when_location_names_are_off_limits():
    class NoNames(Fake):
        def page(self, sql, limit=1000, offset=0):
            if "FROM location" in sql:
                raise NetSuiteError("no permission")
            return super().page(sql, limit, offset)

    stock._working = None
    stock._locations = None
    r = stock.fetch(NoNames(), 11)
    assert r["rows"][0]["location"] == "Location #1" and r["totals"]["available"] == 620.0
    stock._locations = None
