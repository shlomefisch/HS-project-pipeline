"""The timer that keeps the item list fresh. A plain background thread:
one service, nothing extra to deploy. The advisory lock in the sync means
two server processes can't run it at the same time."""

import logging
import threading

from .config import settings

log = logging.getLogger("pipeline.scheduler")
_stop = threading.Event()
FIRST_RUN_DELAY = 60  # seconds after startup, so a deploy settles first


def _loop() -> None:
    from .db import engine
    from .services import item_sync

    wait = FIRST_RUN_DELAY
    while not _stop.wait(wait):
        try:
            item_sync.run(engine)
        except Exception:  # the thread must survive anything
            log.exception("item sync crashed")
        wait = settings.ns_sync_minutes * 60


ABSENCE_EVERY = 600  # seconds: aways start and end within ten minutes of midnight
ABSENCE_LOCK = 815_002


def _absence_loop() -> None:
    from sqlalchemy import text

    from .db import SessionLocal
    from .services import absences

    wait = 30
    while not _stop.wait(wait):
        wait = ABSENCE_EVERY
        db = SessionLocal()
        try:
            if db.scalar(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": ABSENCE_LOCK}):
                if absences.apply_due(db):
                    log.info("aways started/ended")
                db.commit()
        except Exception:
            log.exception("away check failed")
            db.rollback()
        finally:
            db.close()


def start() -> None:
    import os

    if os.environ.get("DISABLE_TIMERS") == "1":  # tests drive these by hand
        return
    _stop.clear()
    threading.Thread(target=_absence_loop, name="aways", daemon=True).start()
    if not settings.netsuite_configured or settings.ns_sync_minutes <= 0:
        log.info("item sync timer off (keys missing or NS_SYNC_MINUTES=0)")
        return
    threading.Thread(target=_loop, name="item-sync", daemon=True).start()


def stop() -> None:
    _stop.set()


def start_in_background(**kwargs) -> None:
    """For the Sync now button: run once without holding up the request."""
    from .db import engine
    from .services import item_sync

    def go():
        try:
            item_sync.run(engine, **kwargs)
        except Exception:
            log.exception("item sync crashed")

    threading.Thread(target=go, name="item-sync-now", daemon=True).start()
