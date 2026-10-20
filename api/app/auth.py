"""Sign-in and who-may-do-what.

People sign in with the email and password an admin set for them
(Google sign-in also works if GOOGLE_CLIENT_ID is set).
What they may do lives here: role, admin flag, active.
"""

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User
from .passwords import hash_password, verify_password
from .rules.constants import WRITER_ROLES

MAX_MISSES = 8
LOCK_FOR = timedelta(minutes=15)
_DUMMY_HASH = hash_password("timing-equalizer")


def _password_version(user: User) -> int:
    # Changing or resetting a password bumps this, which ends every older session.
    # Microseconds: two changes in the same second must still end the older sessions.
    return int(user.password_changed_at.timestamp() * 1_000_000) if user.password_changed_at else 0


def issue_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "pv": _password_version(user),
        "iat": now,
        "exp": now + timedelta(days=settings.token_days),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def password_sign_in(db: Session, email: str, password: str) -> User:
    """Email + password. One vague answer for every miss, so it can't be used to find accounts."""
    wrong = HTTPException(400, "That email and password don't match.")
    user = db.scalar(select(User).where(User.email == email.lower().strip()))
    now = datetime.now(timezone.utc)
    if user is None or not user.password_hash:
        verify_password(password, _DUMMY_HASH)  # same work either way
        raise wrong
    if user.locked_until and user.locked_until > now:
        minutes = max(1, int((user.locked_until - now).total_seconds() // 60) + 1)
        raise HTTPException(429, f"Too many wrong tries. Try again in {minutes} minute(s), or ask an admin to reset the password.")
    db.info["user_id"] = user.id
    if not verify_password(password, user.password_hash):
        user.failed_logins = (user.failed_logins or 0) + 1
        if user.failed_logins >= MAX_MISSES:
            user.locked_until = now + LOCK_FOR
            user.failed_logins = 0
        db.commit()
        raise wrong
    if not user.active:
        raise HTTPException(403, "This account has been deactivated.")
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    db.commit()
    return user


def set_password(user: User, password: str, *, must_change: bool) -> None:
    user.password_hash = hash_password(password)
    user.password_changed_at = datetime.now(timezone.utc)
    user.must_change_password = must_change
    user.failed_logins = 0
    user.locked_until = None


def verify_google_credential(credential: str) -> dict:
    """Checks a Google ID token and returns its claims. Raises 401 if anything is off."""
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    if not settings.google_client_id:
        raise HTTPException(500, "Google sign-in is not configured (GOOGLE_CLIENT_ID).")
    try:
        claims = id_token.verify_oauth2_token(credential, google_requests.Request(), settings.google_client_id)
    except ValueError as exc:
        raise HTTPException(401, f"Google sign-in failed: {exc}") from exc
    email = (claims.get("email") or "").lower()
    if not claims.get("email_verified"):
        raise HTTPException(401, "That Google account's email is not verified.")
    if claims.get("hd", "").lower() != settings.allowed_domain or not email.endswith("@" + settings.allowed_domain):
        raise HTTPException(403, f"Only @{settings.allowed_domain} accounts can sign in.")
    return claims


def sign_in(db: Session, email: str, name: str) -> User:
    """Finds or creates the user on sign-in. New users wait as 'pending' until an admin sets them up."""
    email = email.lower().strip()
    user = db.scalar(select(User).where(User.email == email))
    is_boot_admin = email in settings.admin_emails
    if user is None:
        user = User(
            email=email,
            name=name or email.split("@")[0],
            role="management" if is_boot_admin else "pending",
            is_admin=is_boot_admin,
            active=True,
        )
        db.add(user)
    else:
        if not user.active:
            raise HTTPException(403, "This account has been deactivated.")
        if is_boot_admin and not user.is_admin:
            user.is_admin = True
        if name and not user.name:
            user.name = name
    user.last_login_at = datetime.now(timezone.utc)
    db.flush()
    db.info["user_id"] = user.id
    db.commit()
    return user


def current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Not signed in.")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(401, "Session expired — sign in again.") from exc
    user = db.get(User, user_id)
    if user is None or not user.active:
        raise HTTPException(401, "This account is not active.")
    if payload.get("pv", 0) != _password_version(user):
        raise HTTPException(401, "Your password was changed — sign in again.")
    # The audit log reads this to know who made every change in this request.
    db.info["user_id"] = user.id
    return user


def member(user: User = Depends(current_user)) -> User:
    """Any set-up user. Pending accounts see nothing until an admin assigns a role,
    and someone on a temporary password sees nothing until they pick their own."""
    if user.must_change_password:
        raise HTTPException(403, "Pick your own password first.")
    if user.role == "pending" and not user.is_admin:
        raise HTTPException(403, "Your account is waiting for an admin to set your role.")
    return user


def writer(user: User = Depends(member)) -> User:
    """Anyone who may change things. View-only users can look but not touch."""
    if user.role not in WRITER_ROLES and not user.is_admin:
        raise HTTPException(403, "Your account is view-only.")
    return user


def admin(user: User = Depends(member)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Admins only.")
    return user
