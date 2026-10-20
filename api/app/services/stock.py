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
     "SELECT inl.location AS location, inv.inventorynumber AS lot, "
     "inl.quantityonhand AS onhand, inl.quantityavailable AS available "
     "FROM inventorynumberlocation inl JOIN inventorynumber inv ON inv.id = inl.inventorynumber "
     "WHERE inv.item = {id}"),
    ("balance", True,
     "SELECT ib.location AS location, inv.inventorynumber AS lot, "
     "ib.quantityonhand AS onhand, ib.quantityavailable AS available "
     "FROM inventorybalance ib LEFT JOIN inventorynumber inv ON inv.id = ib.inventorynumber "
     "WHERE ib.item = {id}"),
    ("aggregate", False,
     "SELECT ail.location AS location, ail.quantityonhand AS onhand, "
     "ail.quantityavailable AS available FROM aggregateitemlocation ail WHERE ail.item = {id}"),
    ("item_locations", False,
     "SELECT iil.location AS location, iil.quantityonhand AS onhand, "
     "iil.quantityavailable AS available FROM inventoryitemlocations iil WHERE iil.item = {id}"),
]
# Names looked up on their own: reading a location's name needs its own permission,
# and a missing one must cost only the names, not the numbers.
LOCATION_SQL = "SELECT location.id AS id, location.name AS name FROM location"
LOCATION_CACHE_SECONDS = 3600
_locations: tuple[float, dict[str, str]] | None = None
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


def _location_names(client: SuiteQL) -> dict[str, str]:
    global _locations
    if _locations and time.monotonic() - _locations[0] < LOCATION_CACHE_SECONDS:
        return _locations[1]
    try:
        rows, _ = client.page(LOCATION_SQL)
        names = {str(r["id"]): r.get("name") or f"Location #{r['id']}" for r in rows}
    except NetSuiteError:
        names = {}
    _locations = (time.monotonic(), names)
    return names


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
    names = _location_names(client)
    for r in raw:
        loc = r.get("location")
        r["location"] = names.get(str(loc), f"Location #{loc}") if loc not in (None, "") else None
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
