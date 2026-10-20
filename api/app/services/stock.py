"""Live stock for one item, straight from NetSuite: on hand and still free,
by location and lot. Read-only. Answers are kept for five minutes so a
showroom full of reps opening the same tile doesn't hammer NetSuite."""

import threading
import time

from ..netsuite import NetSuiteError, SuiteQL
from ..timeutil import now

CACHE_SECONDS = 300
_cache: dict[int, tuple[float, dict]] = {}
_lock = threading.Lock()

# NetSuite exposes stock through different tables depending on which features
# an account has turned on. Try each, best first, and remember the one that works.
# No GROUP BY on display values (NetSuite rejects some of those); totals are added up here.
VARIANTS = [
    ("lots", True,
     "SELECT BUILTIN.DISPLAY(inl.location) AS location, inv.inventorynumber AS lot, "
     "inl.quantityonhand AS onhand, inl.quantityavailable AS available "
     "FROM inventorynumberlocation inl JOIN inventorynumber inv ON inv.id = inl.inventorynumber "
     "WHERE inv.item = {id}"),
    ("balance", True,
     "SELECT BUILTIN.DISPLAY(ib.location) AS location, BUILTIN.DISPLAY(ib.inventorynumber) AS lot, "
     "ib.quantityonhand AS onhand, ib.quantityavailable AS available "
     "FROM inventorybalance ib WHERE ib.item = {id}"),
    ("aggregate", False,
     "SELECT BUILTIN.DISPLAY(ail.location) AS location, ail.quantityonhand AS onhand, "
     "ail.quantityavailable AS available FROM aggregateitemlocation ail WHERE ail.item = {id}"),
    ("item_locations", False,
     "SELECT BUILTIN.DISPLAY(iil.location) AS location, iil.quantityonhand AS onhand, "
     "iil.quantityavailable AS available FROM inventoryitemlocations iil WHERE iil.item = {id}"),
]
_working: str | None = None  # name of the variant that last worked
UNIT_SQL = "SELECT BUILTIN.DISPLAY(item.stockunit) AS unit FROM item WHERE item.id = {id}"


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _shape(item_id: int, raw: list[dict], with_lots: bool, unit: str | None) -> dict:
    # Add up per location + lot (a lot can sit in several bins).
    merged: dict[tuple, dict] = {}
    for r in raw:
        key = (r.get("location") or "—", (r.get("lot") or None) if with_lots else None)
        m = merged.setdefault(key, {"location": key[0], "lot": key[1], "on_hand": 0.0, "available": 0.0})
        m["on_hand"] += _num(r.get("onhand"))
        m["available"] += _num(r.get("available"))
    rows = [m for m in merged.values() if m["on_hand"] or m["available"]]
    rows.sort(key=lambda x: (x["location"], -x["available"], x["lot"] or ""))
    return {
        "item_id": item_id,
        "as_of": now().isoformat(),
        "unit": unit,
        "by_lot": with_lots,
        "via": _working,
        "rows": rows,
        "totals": {"on_hand": sum(r["on_hand"] for r in rows), "available": sum(r["available"] for r in rows)},
    }


def fetch(client: SuiteQL, item_id: int) -> dict:
    global _working
    item_id = int(item_id)  # never anything but a number goes into the query
    order = sorted(VARIANTS, key=lambda v: v[0] != _working)
    problems = []
    for name, with_lots, sql in order:
        try:
            raw, _ = client.page(sql.format(id=item_id))
        except NetSuiteError as exc:
            problems.append(f"[{name}] {exc}")
            continue
        _working = name
        break
    else:
        raise NetSuiteError(" | ".join(problems))
    try:
        units, _ = client.page(UNIT_SQL.format(id=item_id), limit=1)
        unit = (units[0].get("unit") if units else None) or None
    except NetSuiteError:
        unit = None
    return _shape(item_id, raw, with_lots, unit)


def get(client_factory, item_id: int, fresh: bool = False) -> dict:
    with _lock:
        hit = _cache.get(item_id)
    if hit and not fresh and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    result = fetch(client_factory(), item_id)
    with _lock:
        _cache[item_id] = (time.monotonic(), result)
    return result
