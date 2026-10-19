"""Copies NetSuite's inventory items into the local items table.

Read-only toward NetSuite. Runs on a timer and from the Sync now button.
- "full": every inventory item; anything no longer returned is marked inactive.
- "changes": only items modified since the day before the last good run.
Upserts are idempotent, so overlapping windows are harmless.
"""

import logging
from datetime import timedelta

from sqlalchemy import Engine, func, insert, select, text, update
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
    "SELECT item.id, item.itemid, item.displayname, item.isinactive, item.islotitem "
    "FROM item WHERE item.itemtype = 'InvtPart' AND item.id > {after}{since} ORDER BY item.id"
)


def client_from_settings() -> SuiteQL:
    if not settings.netsuite_configured:
        raise NetSuiteError("NetSuite keys aren't set. Add the five NS_ variables on Railway.")
    return SuiteQL(Keys(settings.ns_account, settings.ns_consumer_key, settings.ns_consumer_secret,
                        settings.ns_token_id, settings.ns_token_secret))


def to_item(r: dict) -> dict:
    """One SuiteQL row -> one items row. NetSuite booleans come back as 'T'/'F'."""
    code = (r.get("itemid") or "").strip()
    display = (r.get("displayname") or "").strip()
    name = display or code or f"Item #{r['id']}"
    return {
        "netsuite_id": int(r["id"]),
        "name": name,
        "sku": code if code and code != name else None,
        "active": r.get("isinactive") != "T",
        "is_lot": r.get("islotitem") == "T",
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
        for page in client.by_id(lambda after: ITEM_SQL.format(after=after, since=since)):
            rows = [to_item(r) for r in page]
            stmt = pg_insert(items).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=[items.c.netsuite_id],
                set_={
                    "name": stmt.excluded.name,
                    "sku": stmt.excluded.sku,
                    "active": stmt.excluded.active,
                    "is_lot": stmt.excluded.is_lot,
                    "synced_at": func.now(),
                },
            )
            with engine.begin() as conn:
                conn.execute(stmt)
                seen += len(rows)
                conn.execute(update(runs).where(runs.c.id == run_id).values(rows_seen=seen))
        retired = 0
        if mode == "full":
            with engine.begin() as conn:
                # Gone from NetSuite's inventory list: keep the row (old jobs point at it), hide it from search.
                retired = conn.execute(
                    update(items).where(items.c.active.is_(True), items.c.synced_at < started).values(active=False)
                ).rowcount
        with engine.begin() as conn:
            conn.execute(update(runs).where(runs.c.id == run_id).values(status="ok", finished_at=now(), rows_seen=seen))
        log.info("item sync %s ok: %s rows, %s retired", mode, seen, retired)
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
