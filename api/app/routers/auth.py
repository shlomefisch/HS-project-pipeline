from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import current_user, issue_token, sign_in, verify_google_credential
from ..config import settings
from ..db import get_db
from ..models import User
from ..schemas import DevSignIn, GoogleSignIn
from ..serialize import user_out

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/google")
def google_sign_in(body: GoogleSignIn, db: Session = Depends(get_db)):
    claims = verify_google_credential(body.credential)
    user = sign_in(db, claims["email"], claims.get("name") or "")
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
