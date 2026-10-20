"""NetSuite sync status and the Sync now button (admins)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .. import scheduler
from ..auth import admin
from ..config import settings
from ..db import get_db
from ..models import Item, SyncRun, User
from ..serialize import row
from ..services.item_sync import LOCK_KEY

router = APIRouter(tags=["sync"])


@router.get("/sync/items")
def item_sync_status(db: Session = Depends(get_db), _: User = Depends(admin)):
    runs = db.scalars(select(SyncRun).where(SyncRun.kind == "items").order_by(SyncRun.started_at.desc()).limit(8)).all()
    return {
        "configured": settings.netsuite_configured,
        "every_minutes": settings.ns_sync_minutes,
        "items_active": db.scalar(select(func.count()).select_from(Item).where(Item.active.is_(True))),
        "items_total": db.scalar(select(func.count()).select_from(Item)),
        "items_stock": db.scalar(select(func.count()).select_from(Item).where(Item.active.is_(True), Item.is_stock.is_(True))),
        "items_with_unit": db.scalar(
            select(func.count()).select_from(Item).where(Item.active.is_(True), Item.is_stock.is_(True), Item.unit.is_not(None))
        ),
        "running": any(r.status == "running" for r in runs[:1]),
        "runs": [row(r) for r in runs],
    }


@router.post("/sync/items", status_code=202)
def item_sync_now(full: bool = False, db: Session = Depends(get_db), user: User = Depends(admin)):
    if not settings.netsuite_configured:
        raise HTTPException(409, "NetSuite keys aren't set yet. Add the five NS_ variables on Railway.")
    # Quick check so the button can say "already running" instead of silently doing nothing.
    free = db.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY})
    if not free:
        raise HTTPException(409, "A sync is already running.")
    db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
    db.rollback()
    scheduler.start_in_background(mode="full" if full else None, user_id=user.id)
    return {"started": True}
