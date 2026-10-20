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

# Per location and lot. Lot-tracked items get one row per lot; others one per location.
BY_LOT_SQL = (
    "SELECT BUILTIN.DISPLAY(ib.location) AS location, BUILTIN.DISPLAY(ib.inventorynumber) AS lot, "
    "SUM(ib.quantityonhand) AS onhand, SUM(ib.quantityavailable) AS available "
    "FROM inventorybalance ib WHERE ib.item = {id} "
    "GROUP BY BUILTIN.DISPLAY(ib.location), BUILTIN.DISPLAY(ib.inventorynumber)"
)
# Fallback if the role can't read inventory balances: per location, no lots.
BY_LOCATION_SQL = (
    "SELECT BUILTIN.DISPLAY(iil.location) AS location, iil.quantityonhand AS onhand, "
    "iil.quantityavailable AS available FROM inventoryitemlocations iil WHERE iil.item = {id}"
)
UNIT_SQL = "SELECT BUILTIN.DISPLAY(item.stockunit) AS unit FROM item WHERE item.id = {id}"


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _shape(item_id: int, raw: list[dict], with_lots: bool, unit: str | None) -> dict:
    rows = []
    for r in raw:
        on_hand, available = _num(r.get("onhand")), _num(r.get("available"))
        if on_hand == 0 and available == 0:
            continue
        rows.append({
            "location": r.get("location") or "—",
            "lot": (r.get("lot") or None) if with_lots else None,
            "on_hand": on_hand,
            "available": available,
        })
    rows.sort(key=lambda x: (x["location"], -x["available"], x["lot"] or ""))
    return {
        "item_id": item_id,
        "as_of": now().isoformat(),
        "unit": unit,
        "by_lot": with_lots,
        "rows": rows,
        "totals": {"on_hand": sum(r["on_hand"] for r in rows), "available": sum(r["available"] for r in rows)},
    }


def fetch(client: SuiteQL, item_id: int) -> dict:
    item_id = int(item_id)  # never anything but a number goes into the query
    try:
        raw, _ = client.page(BY_LOT_SQL.format(id=item_id))
        with_lots = True
    except NetSuiteError:
        raw, _ = client.page(BY_LOCATION_SQL.format(id=item_id))
        with_lots = False
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
