from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import User
from ..schemas import LoginIn, PasswordIn, ProfileIn, SignupIn
from ..security import COOKIE, auth_limiter, create_token, current_user, hash_password, verify_password
from ..services.farm_service import log

router = APIRouter(prefix="/api/auth", tags=["auth"])


def ser_user(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "preferences": u.preferences or {},
            "created_at": u.created_at.isoformat()}


def _set_cookie(resp: Response, token: str) -> None:
    s = get_settings()
    resp.set_cookie(COOKIE, token, httponly=True, samesite="lax", secure=s.cookie_secure,
                    max_age=s.access_token_minutes * 60, path="/")


@router.post("/signup", status_code=201, dependencies=[Depends(auth_limiter)])
def signup(body: SignupIn, response: Response, db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists")
    u = User(email=email, name=body.name.strip(), password_hash=hash_password(body.password),
             preferences={"display_unit": "ft", "theme": "light"})
    db.add(u)
    db.commit()
    log(db, u, None, "signup")
    db.commit()
    token = create_token(u)
    _set_cookie(response, token)
    return {"user": ser_user(u), "token": token}


@router.post("/login", dependencies=[Depends(auth_limiter)])
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(User.email == body.email.lower()))
    if not u or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, "Incorrect email or password")
    u.last_login_at = datetime.now(timezone.utc)
    log(db, u, None, "login")
    db.commit()
    token = create_token(u)
    _set_cookie(response, token)
    return {"user": ser_user(u), "token": token}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return ser_user(user)


@router.patch("/me")
def update_me(body: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.name is not None:
        user.name = body.name.strip()
    if body.preferences is not None:
        allowed = {"display_unit", "theme", "temperature_unit", "dense_tables"}
        user.preferences = {**(user.preferences or {}), **{k: v for k, v in body.preferences.items() if k in allowed}}
    db.commit()
    return ser_user(user)


@router.post("/change-password")
def change_password(body: PasswordIn, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1  # revoke other sessions
    db.commit()
    _set_cookie(response, create_token(user))
    return {"ok": True}
