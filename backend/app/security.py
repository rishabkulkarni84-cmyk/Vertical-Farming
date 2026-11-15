"""Password hashing (bcrypt), JWT sessions in an httpOnly cookie (or Bearer header), CSRF header check, rate limit."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import User

COOKIE = "verdant_session"
CSRF_HEADER = "x-requested-with"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode()[:72], bcrypt.gensalt(rounds=12)).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode()[:72], hashed.encode())
    except ValueError:
        return False


def create_token(user: User) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user.id), "ver": user.token_version, "iat": now, "exp": now + timedelta(minutes=s.access_token_minutes)}
    return jwt.encode(payload, s.secret_key, algorithm="HS256")


def _token_from(request: Request) -> tuple[str | None, bool]:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:], False
    return request.cookies.get(COOKIE), True


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token, via_cookie = _token_from(request)
    if not token:
        raise HTTPException(401, "Not signed in")
    if via_cookie and request.method in UNSAFE and request.headers.get(CSRF_HEADER) != "verdant":
        raise HTTPException(403, "Missing CSRF header")
    try:
        data = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Session expired or invalid") from None
    user = db.get(User, int(data["sub"]))
    if not user or user.token_version != data.get("ver"):
        raise HTTPException(401, "Session expired or invalid")
    return user


class RateLimiter:
    """Simple in-process sliding-window limiter for sensitive endpoints (per client IP)."""

    def __init__(self, limit: int, window_s: int):
        self.limit, self.window = limit, window_s
        self.hits: dict[str, deque] = defaultdict(deque)

    def __call__(self, request: Request) -> None:
        if get_settings().environment == "test":
            return
        key = f"{request.url.path}:{request.client.host if request.client else 'unknown'}"
        q, now = self.hits[key], time.monotonic()
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            raise HTTPException(429, "Too many attempts. Please wait a minute and try again.")
        q.append(now)


auth_limiter = RateLimiter(limit=10, window_s=60)
