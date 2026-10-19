from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import current_user, issue_token, password_sign_in, set_password, sign_in, verify_google_credential
from ..config import settings
from ..db import get_db
from ..models import User
from ..passwords import problem_with, verify_password
from ..schemas import DevSignIn, GoogleSignIn, PasswordChange, PasswordSignIn
from ..serialize import user_out

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/google")
def google_sign_in(body: GoogleSignIn, db: Session = Depends(get_db)):
    claims = verify_google_credential(body.credential)
    user = sign_in(db, claims["email"], claims.get("name") or "")
    return {"token": issue_token(user), "user": user_out(user)}


@router.post("/login")
def login(body: PasswordSignIn, db: Session = Depends(get_db)):
    user = password_sign_in(db, body.email, body.password)
    return {"token": issue_token(user), "user": user_out(user)}


@router.post("/password")
def change_password(body: PasswordChange, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Your own password. Needs the current one, unless you never had one (first-time setup).
    Returns a fresh session: the change ends every other one."""
    if user.password_hash and not verify_password(body.current_password, user.password_hash):
        # 400, not 401: a typo here must not sign you out.
        raise HTTPException(400, "The current password isn't right.")
    problem = problem_with(body.new_password)
    if problem:
        raise HTTPException(422, problem)
    if user.password_hash and verify_password(body.new_password, user.password_hash):
        raise HTTPException(422, "Pick a password different from the current one.")
    set_password(user, body.new_password, must_change=False)
    db.commit()
    return {"token": issue_token(user), "user": user_out(user)}


@router.post("/dev")
def dev_sign_in(body: DevSignIn, db: Session = Depends(get_db)):
    """Testing only — switched off unless DEV_LOGIN=1."""
    if not settings.dev_login:
        raise HTTPException(404, "Not found.")
    email = body.email.strip().lower()
    if not email.endswith("@" + settings.allowed_domain):
        raise HTTPException(403, f"Only @{settings.allowed_domain} accounts can sign in.")
    user = sign_in(db, email, body.name or "")
    return {"token": issue_token(user), "user": user_out(user)}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_out(user)
