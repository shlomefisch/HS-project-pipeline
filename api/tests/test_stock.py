"""Live stock lookup, against a stand-in NetSuite."""

from app.netsuite import NetSuiteError
from app.services import stock


class Fake:
    def __init__(self, lots_ok=True):
        self.lots_ok = lots_ok
        self.sql = []

    def page(self, sql, limit=1000, offset=0):
        self.sql.append(sql)
        if "inventorybalance" in sql:
            if not self.lots_ok:
                raise NetSuiteError("not allowed")
            return [
                {"location": "Newark", "lot": "L-204", "onhand": "300", "available": "120"},
                {"location": "Newark", "lot": "L-311", "onhand": 500, "available": 500},
                {"location": "Monsey", "lot": "L-204", "onhand": 0, "available": 0},
            ], False
        if "inventoryitemlocations" in sql:
            return [{"location": "Newark", "onhand": 800, "available": 620}], False
        return [{"unit": "SF"}], False


def test_by_lot_with_totals_and_empty_rows_dropped():
    r = stock.fetch(Fake(), 11)
    assert r["by_lot"] and r["unit"] == "SF"
    assert [x["lot"] for x in r["rows"]] == ["L-311", "L-204"]  # most free first
    assert r["totals"] == {"on_hand": 800.0, "available": 620.0}


def test_falls_back_to_locations_when_lots_are_not_readable():
    r = stock.fetch(Fake(lots_ok=False), 11)
    assert not r["by_lot"] and r["rows"] == [{"location": "Newark", "lot": None, "on_hand": 800.0, "available": 620.0}]


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
    assert jay.get("/api/items/11/stock").status_code == 409
