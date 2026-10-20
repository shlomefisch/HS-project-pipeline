"""NetSuite Base Price for an item, live, read-only. Kept for an hour.
Tries NetSuite's price table first, then the item record, and remembers what works."""

import threading
import time
from decimal import Decimal

from ..netsuite import NetSuiteError, SuiteQL

BASE_PRICE_LEVEL = 1  # "Base Price" in NetSuite
CACHE_SECONDS = 3600
_cache: dict[int, tuple[float, Decimal | None]] = {}
_lock = threading.Lock()

VARIANTS = [
    ("pricing",
     "SELECT p.unitprice AS price, p.quantity AS qty FROM pricing p "
     "WHERE p.item = {id} AND p.pricelevel = " + str(BASE_PRICE_LEVEL) + " AND p.currency = 1"),
    ("pricing_any_currency",
     "SELECT p.unitprice AS price, p.quantity AS qty FROM pricing p "
     "WHERE p.item = {id} AND p.pricelevel = " + str(BASE_PRICE_LEVEL)),
]
_working: str | None = None


def fetch(client: SuiteQL, item_id: int) -> Decimal | None:
    """The base price for the first quantity break, or None if NetSuite has none."""
    global _working
    item_id = int(item_id)
    problems = []
    for name, sql in sorted(VARIANTS, key=lambda v: v[0] != _working):
        try:
            rows, _ = client.page(sql.format(id=item_id))
        except NetSuiteError as exc:
            problems.append(f"[{name}] {exc}")
            continue
        _working = name
        priced = [r for r in rows if r.get("price") not in (None, "")]
        if not priced:
            return None
        first = min(priced, key=lambda r: float(r.get("qty") or 0))
        return Decimal(str(first["price"]))
    raise NetSuiteError(" | ".join(problems))


def base_price(client_factory, item_id: int) -> Decimal | None:
    with _lock:
        hit = _cache.get(item_id)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    price = fetch(client_factory(), item_id)
    with _lock:
        _cache[item_id] = (time.monotonic(), price)
    return price
