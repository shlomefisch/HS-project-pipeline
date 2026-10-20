"""Copies NetSuite's inventory items into the local items table.

Read-only toward NetSuite. Runs on a timer and from the Sync now button.
- "full": every inventory item; anything no longer returned is marked inactive.
- "changes": only items modified since the day before the last good run.
Upserts are idempotent, so overlapping windows are harmless.
"""

import logging
from datetime import timedelta

from sqlalchemy import Engine, case, func, insert, literal, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..config import settings
from ..models import Item, SyncRun
from ..netsuite import Keys, NetSuiteError, SuiteQL
from ..timeutil import TZ, now

log = logging.getLogger("pipeline.sync")

LOCK_KEY = 815_001  # Postgres advisory lock: one item sync at a time, across every server process
FULL_EVERY = timedelta(hours=20)
STALE_RUN = timedelta(hours=2)

ITEM_SQL = (
    "SELECT item.id, item.itemid, item.displayname, item.isinactive, item.islotitem, "
    "item.custitem4, item.{unit_field} AS unitref "
    "FROM item WHERE item.itemtype = 'InvtPart' AND item.id > {after}{since} ORDER BY item.id"
)


def client_from_settings() -> SuiteQL:
    if not settings.netsuite_configured:
        raise NetSuiteError("NetSuite keys aren't set. Add the five NS_ variables on Railway.")
    return SuiteQL(Keys(settings.ns_account, settings.ns_consumer_key, settings.ns_consumer_secret,
                        settings.ns_token_id, settings.ns_token_secret))


# Unit names (SF, PC, ...) by unit id. Read on its own: if the role can't see units,
# the sync still works and only the unit labels are missing.
UNIT_SQL = "SELECT u.internalid AS id, u.abbreviation AS abbr, u.unitname AS name FROM unitstypeuom u"


# The unit field: baseunit if NetSuite lets queries read it, else stockunit.
UNIT_FIELDS = ("baseunit", "stockunit")


PHOTO_FIELD = "custitem_atlas_item_image_2"


def photo_field_readable(client) -> bool:
    try:
        client.page(f"SELECT item.id, item.{PHOTO_FIELD} FROM item WHERE item.itemtype = 'InvtPart'", limit=1)
        return True
    except NetSuiteError as exc:
        log.warning("photo field not readable: %s", exc)
        return False


def resolve_photos(engine, client, keys) -> int:
    """Looks up the web address of each new photo file. A file NetSuite won't
    show us just stays without a picture; the sync carries on either way."""
    items = Item.__table__
    with engine.connect() as c:
        todo = [r[0] for r in c.execute(
            select(items.c.image_file_id).where(items.c.image_file_id.is_not(None), items.c.image_url.is_(None)).distinct()
        )]
    host = f"https://{keys.account.lower().replace('_', '-')}.app.netsuite.com" if keys else ""
    found = 0
    for i in range(0, len(todo), 200):
        batch = todo[i:i + 200]
        try:
            rows, _ = client.page(f"SELECT f.id AS id, f.url AS url FROM file f WHERE f.id IN ({', '.join(str(int(x)) for x in batch)})")
        except NetSuiteError as exc:
            log.warning("photo addresses unavailable: %s", exc)
            return found
        with engine.begin() as c:
            for r in rows:
                url = (r.get("url") or "").strip()
                if not url:
                    continue
                full = url if url.startswith("http") else host + url
                c.execute(update(items).where(items.c.image_file_id == int(r["id"])).values(image_url=full))
                found += 1
    return found


def pick_unit_field(client) -> str | None:
    for field in UNIT_FIELDS:
        try:
            client.page(f"SELECT item.id, item.{field} FROM item WHERE item.itemtype = 'InvtPart'", limit=1)
            return field
        except NetSuiteError as exc:
            log.warning("unit field %s not readable: %s", field, exc)
    return None


def unit_names(client, unit_field: str | None) -> dict[int, str]:
    """Unit id -> label. First from the units table; if that's off limits,
    from the display value of the item's own unit field."""
    names: dict[int, str] = {}
    try:
        for page in client.by_id(lambda after: f"{UNIT_SQL} WHERE u.internalid > {after} ORDER BY u.internalid"):
            for r in page:
                label = (r.get("abbr") or r.get("name") or "").strip()
                if label:
                    names[int(r["id"])] = label
    except NetSuiteError as exc:
        log.warning("units table unavailable: %s", exc)
    if names or not unit_field:
        return names
    try:
        rows, _ = client.page(
            f"SELECT item.{unit_field} AS id, BUILTIN.DISPLAY(item.{unit_field}) AS abbr FROM item "
            f"WHERE item.{unit_field} IS NOT NULL GROUP BY item.{unit_field}, BUILTIN.DISPLAY(item.{unit_field})"
        )
        for r in rows:
            label, uid = (r.get("abbr") or "").strip(), _int(r.get("id"))
            if label and uid is not None:
                names[uid] = label
    except NetSuiteError as exc:
        log.warning("unit labels unavailable: %s", exc)
    return names


def _int(v) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def to_item(r: dict, units: dict[int, str] | None = None) -> dict:
    """One SuiteQL row -> one items row. NetSuite booleans come back as 'T'/'F'."""
    code = (r.get("itemid") or "").strip()
    display = (r.get("displayname") or "").strip()
    name = display or code or f"Item #{r['id']}"
    unit_id = _int(r.get("unitref", r.get("stockunit")))
    image_id = _int(r.get("imageref"))
    return {
        "netsuite_id": int(r["id"]),
        "name": name,
        "sku": code if code and code != name else None,
        "active": r.get("isinactive") != "T",
        "is_lot": r.get("islotitem") == "T",
        "is_stock": r.get("custitem4") == "T",
        "unit_id": unit_id,
        "unit": (units or {}).get(unit_id) if unit_id is not None else None,
        "image_file_id": image_id,
    }


def _pick_mode(conn, requested: str | None) -> tuple[str, str]:
    """Returns (mode, extra WHERE clause)."""
    if requested == "full":
        return "full", ""
    last_full = conn.scalar(
        select(func.max(SyncRun.started_at)).where(SyncRun.kind == "items", SyncRun.mode == "full", SyncRun.status == "ok")
    )
    if last_full is None or (requested is None and now() - last_full > FULL_EVERY):
        return "full", ""
    last_ok = conn.scalar(select(func.max(SyncRun.started_at)).where(SyncRun.kind == "items", SyncRun.status == "ok"))
    since = (last_ok.astimezone(TZ) - timedelta(days=1)).date().isoformat()
    return "changes", f" AND item.lastmodifieddate >= TO_DATE('{since}', 'YYYY-MM-DD')"


def run(engine: Engine, client: SuiteQL | None = None, mode: str | None = None, user_id: int | None = None) -> dict:
    """One sync. Returns {"status": "ok"|"failed"|"busy", ...}. Never raises for NetSuite trouble."""
    with engine.connect() as lock_conn:
        if not lock_conn.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}):
            return {"status": "busy"}
        try:
            return _run_locked(engine, client, mode, user_id)
        finally:
            lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            lock_conn.commit()


def _run_locked(engine: Engine, client: SuiteQL | None, requested: str | None, user_id: int | None) -> dict:
    runs = SyncRun.__table__
    items = Item.__table__
    with engine.begin() as conn:
        # A run that died with the server never finished; close it out.
        conn.execute(
            update(runs)
            .where(runs.c.status == "running", runs.c.started_at < now() - STALE_RUN)
            .values(status="failed", finished_at=now(), error="Stopped before finishing (server restarted).")
        )
        mode, since = _pick_mode(conn, requested)
        run_id = conn.scalar(insert(runs).values(kind="items", mode=mode, started_by=user_id).returning(runs.c.id))
        started = conn.scalar(select(runs.c.started_at).where(runs.c.id == run_id))

    seen = 0
    try:
        client = client or client_from_settings()
        unit_field = pick_unit_field(client)
        units = unit_names(client, unit_field)
        item_sql = ITEM_SQL if unit_field else ITEM_SQL.replace(", item.{unit_field} AS unitref", "")
        photos = photo_field_readable(client)
        if photos:
            item_sql = item_sql.replace(" FROM item WHERE", f", item.{PHOTO_FIELD} AS imageref FROM item WHERE", 1)
        for page in client.by_id(lambda after: item_sql.format(after=after, since=since, unit_field=unit_field)):
            rows = [to_item(r, units) for r in page]
            stmt = pg_insert(items).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=[items.c.netsuite_id],
                set_={
                    "name": stmt.excluded.name,
                    "sku": stmt.excluded.sku,
                    "active": stmt.excluded.active,
                    "is_lot": stmt.excluded.is_lot,
                    "is_stock": stmt.excluded.is_stock,
                    "unit_id": stmt.excluded.unit_id,
                    # Keep a known label if this run couldn't read unit names.
                    "unit": func.coalesce(stmt.excluded.unit, items.c.unit),
                    # A new photo file means its address has to be looked up again.
                    "image_file_id": func.coalesce(stmt.excluded.image_file_id, items.c.image_file_id) if not photos else stmt.excluded.image_file_id,
                    "image_url": case(
                        (items.c.image_file_id.is_distinct_from(stmt.excluded.image_file_id) if photos else literal(False), None),
                        else_=items.c.image_url,
                    ),
                    "synced_at": func.now(),
                },
            )
            with engine.begin() as conn:
                conn.execute(stmt)
                seen += len(rows)
                conn.execute(update(runs).where(runs.c.id == run_id).values(rows_seen=seen))
        photo_urls = resolve_photos(engine, client, getattr(client, "keys", None)) if photos else 0
        retired = 0
        if mode == "full":
            with engine.begin() as conn:
                # Gone from NetSuite's inventory list: keep the row (old jobs point at it), hide it from search.
                retired = conn.execute(
                    update(items).where(items.c.active.is_(True), items.c.synced_at < started).values(active=False)
                ).rowcount
        with engine.begin() as conn:
            conn.execute(update(runs).where(runs.c.id == run_id).values(status="ok", finished_at=now(), rows_seen=seen))
        log.info("item sync %s ok: %s rows, %s retired, %s photo addresses", mode, seen, retired, photo_urls)
        return {"status": "ok", "mode": mode, "rows": seen, "retired": retired}
    except Exception as exc:  # recorded for the Team screen, never crashes the server
        message = str(exc) if isinstance(exc, NetSuiteError) else f"{type(exc).__name__}: {exc}"
        log.warning("item sync %s failed: %s", mode, message)
        with engine.begin() as conn:
            conn.execute(
                update(runs).where(runs.c.id == run_id)
                .values(status="failed", finished_at=now(), rows_seen=seen, error=message[:2000])
            )
        return {"status": "failed", "mode": mode, "rows": seen, "error": message}
