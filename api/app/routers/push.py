"""Turning phone notifications on and off."""

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import User
from ..schemas import _In
from ..services import push

router = APIRouter(prefix="/push", tags=["push"])


class Keys(_In):
    p256dh: str
    auth: str


class Subscription(_In):
    endpoint: str
    keys: Keys
    expirationTime: float | None = None


class Unsubscribe(_In):
    endpoint: str


@router.get("/key")
def public_key(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return {"key": push.keys(db)[1]}


@router.get("/status")
def status(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return {"phones": push.count(db, user.id)}


@router.post("/subscribe")
def subscribe(body: Subscription, user_agent: str | None = Header(default=None), db: Session = Depends(get_db), user: User = Depends(current_user)):
    push.subscribe(db, user.id, body.endpoint, body.keys.p256dh, body.keys.auth, (user_agent or "")[:300])
    db.commit()
    return {"phones": push.count(db, user.id)}


@router.post("/unsubscribe")
def unsubscribe(body: Unsubscribe, db: Session = Depends(get_db), _: User = Depends(current_user)):
    push.unsubscribe(db, body.endpoint)
    db.commit()
    return {"ok": True}


@router.post("/test")
def test(user: User = Depends(current_user)):
    push.enqueue(user.id, "Notifications are on", "This is what a next step will look like.", "/#/today")
    return {"sent": True}
