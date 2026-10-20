"""Phone notifications (web push).

Who gets buzzed is decided in one place, from what was just saved:
- a new task with severity notify/interrupt, given by someone else -> its assignee
- a task turning into a bad answer or blocked for the rep          -> the job's rep
- something logged on a job by someone other than its rep           -> the rep
Sending happens after the save is committed, off the request, so a slow or
blocked push service never slows anyone down.
"""

import base64
import json
import logging
import os
import queue
import threading

from sqlalchemy import delete, event, inspect, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..models import AppSetting, Event, Job, PushSubscription, Task, User
from ..timeutil import now

log = logging.getLogger("pipeline.push")

_q: "queue.Queue[dict]" = queue.Queue(maxsize=1000)
_worker: threading.Thread | None = None
_keys: tuple[str, str] | None = None  # (private PEM, public base64url)
CONTACT = "mailto:admin@hstile.com"


# ----------------------------------------------------------------- keys
def keys(db: Session) -> tuple[str, str]:
    """The server's VAPID key pair: made once, kept in app_settings (outside the audit log)."""
    global _keys
    if _keys:
        return _keys
    t = AppSetting.__table__
    got = dict(db.execute(select(t.c.key, t.c.value).where(t.c.key.in_(("vapid_private_pem", "vapid_public")))).all())
    if not got.get("vapid_private_pem"):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        priv = ec.generate_private_key(ec.SECP256R1())
        pem = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
        raw = priv.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        pub = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
        for k, v in (("vapid_private_pem", pem), ("vapid_public", pub)):
            db.execute(pg_insert(t).values(key=k, value=v).on_conflict_do_nothing(index_elements=[t.c.key]))
        db.commit()
        got = dict(db.execute(select(t.c.key, t.c.value).where(t.c.key.in_(("vapid_private_pem", "vapid_public")))).all())
    _keys = (got["vapid_private_pem"], got["vapid_public"])
    return _keys


# -------------------------------------------------------- subscriptions
def subscribe(db: Session, user_id: int, endpoint: str, p256dh: str, auth: str, user_agent: str | None) -> None:
    t = PushSubscription.__table__
    stmt = pg_insert(t).values(user_id=user_id, endpoint=endpoint, p256dh=p256dh, auth=auth, user_agent=user_agent)
    db.execute(stmt.on_conflict_do_update(
        index_elements=[t.c.endpoint],
        set_={"user_id": user_id, "p256dh": p256dh, "auth": auth, "user_agent": user_agent, "failures": 0},
    ))


def unsubscribe(db: Session, endpoint: str) -> None:
    db.execute(delete(PushSubscription.__table__).where(PushSubscription.__table__.c.endpoint == endpoint))


def count(db: Session, user_id: int) -> int:
    t = PushSubscription.__table__
    return len(db.execute(select(t.c.id).where(t.c.user_id == user_id)).all())


# --------------------------------------------------------------- send
def enqueue(user_id: int, title: str, body: str, url: str, urgent: bool = False) -> None:
    try:
        _q.put_nowait({"user_id": user_id, "title": title, "body": body, "url": url, "urgent": urgent})
    except queue.Full:
        log.warning("push queue full; dropping a notification")
    _ensure_worker()


def _ensure_worker() -> None:
    global _worker
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_work, name="push", daemon=True)
        _worker.start()


def _work() -> None:
    from ..db import SessionLocal

    while True:
        msg = _q.get()
        db = SessionLocal()
        try:
            deliver(db, msg)
            db.commit()
        except Exception:
            log.exception("push failed")
            db.rollback()
        finally:
            db.close()


def deliver(db: Session, msg: dict, sender=None) -> int:
    """Sends one notification to every phone of one user. Returns how many took it."""
    t = PushSubscription.__table__
    subs = db.execute(select(t).where(t.c.user_id == msg["user_id"])).mappings().all()
    if not subs:
        return 0
    if sender is None:
        from pywebpush import webpush as sender
    from py_vapid import Vapid

    pem, _ = keys(db)
    vapid = Vapid.from_pem(pem.encode())
    payload = json.dumps({k: msg[k] for k in ("title", "body", "url", "urgent")})
    ok = 0
    for s in subs:
        try:
            sender(
                subscription_info={"endpoint": s["endpoint"], "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}},
                data=payload,
                vapid_private_key=vapid,
                vapid_claims={"sub": CONTACT},
                ttl=24 * 3600,
                headers={"Urgency": "high" if msg.get("urgent") else "normal"},
            )
            db.execute(update(t).where(t.c.id == s["id"]).values(last_sent_at=now(), failures=0))
            ok += 1
        except Exception as exc:  # pywebpush.WebPushException, or the network
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):  # the phone unsubscribed or reinstalled: forget it
                db.execute(delete(t).where(t.c.id == s["id"]))
            else:
                db.execute(update(t).where(t.c.id == s["id"]).values(failures=t.c.failures + 1))
                log.warning("push to user %s failed (%s): %s", msg["user_id"], status, exc)
    return ok


# ------------------------------------------- who gets buzzed, and when
def _pending(session: Session) -> list[tuple]:
    return session.info.setdefault("push_pending", [])


@event.listens_for(Session, "after_flush")
def _collect(session: Session, flush_context) -> None:
    pend = _pending(session)
    for obj in session.new:
        if isinstance(obj, Task) and obj.severity in ("notify", "interrupt") and obj.assignee_id != obj.created_by:
            pend.append(("task", obj.id))
        elif isinstance(obj, Event) and obj.logged_by is not None:
            pend.append(("event", obj.id))
    for obj in session.dirty:
        if isinstance(obj, Task) and obj.needs_rep_attention:
            hist = inspect(obj).attrs.needs_rep_attention.history
            if hist.added and True in hist.added and not (hist.deleted and True in hist.deleted):
                pend.append(("bad", obj.id))


@event.listens_for(Session, "after_commit")
def _send(session: Session) -> None:
    pend = session.info.pop("push_pending", [])
    if not pend or os.environ.get("DISABLE_PUSH") == "1":  # tests call plan_message / deliver directly
        return
    # Resolve names after the commit, in a fresh session; never fail the save over a notification.
    threading.Thread(target=_resolve, args=(pend,), daemon=True).start()


@event.listens_for(Session, "after_rollback")
def _drop(session: Session) -> None:
    session.info.pop("push_pending", None)


def _resolve(pend: list[tuple]) -> None:
    from ..db import SessionLocal

    db = SessionLocal()
    try:
        for kind, oid in dict.fromkeys(pend):
            for user_id, title, body, url, urgent in plan_message(db, kind, oid):
                enqueue(user_id, title, body, url, urgent)
    except Exception:
        log.exception("push planning failed")
    finally:
        db.close()


def plan_message(db: Session, kind: str, oid: int) -> list[tuple]:
    """(user_id, title, body, url, urgent) for one thing that happened."""
    if kind in ("task", "bad"):
        t = db.get(Task, oid)
        if t is None:
            return []
        job = db.get(Job, t.job_id)
        url = f"/#/jobs/{job.id}"
        if kind == "task":
            by = db.get(User, t.created_by) if t.created_by else None
            who = by.name if by else "Someone"
            return [(t.assignee_id, f"Next step for you — {job.name}", f"{t.title} (from {who}, due {t.due_date:%b} {t.due_date.day})", url, t.severity == "interrupt")]
        owner = job.rep_id
        if t.order_id:
            from ..models import Order

            o = db.get(Order, t.order_id)
            if o is not None and o.handler_id:
                owner = o.handler_id
        if owner == t.completed_by:
            return []
        label = "Bad answer" if t.status == "bad_answer" else "Blocked"
        return [(owner, f"{label} — {job.name}", f"{t.title}: {t.outcome_note or ''}".strip(), url, True)]
    if kind == "event":
        e = db.get(Event, oid)
        if e is None:
            return []
        job = db.get(Job, e.job_id)
        if job is None or e.logged_by == job.rep_id:
            return []
        by = db.get(User, e.logged_by)
        return [(job.rep_id, f"{by.name if by else 'Someone'} logged on {job.name}", e.summary, f"/#/jobs/{job.id}", False)]
    return []
