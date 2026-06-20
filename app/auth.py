from __future__ import annotations

import time
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from passlib.context import CryptContext
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import User

MIN_PASSWORD_LENGTH = 12

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto", pbkdf2_sha256__rounds=600_000)
login_failures: dict[tuple[str, str], list[float]] = {}


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def users_exist(db: Session) -> bool:
    return bool(db.scalar(select(func.count(User.id))))


def create_user(
    db: Session,
    *,
    username: str,
    password: str,
    display_name: str | None = None,
    is_admin: bool = False,
) -> User:
    username_clean = username.strip().lower()
    display_name_clean = (display_name or username).strip()
    if not username_clean:
        raise ValueError("Username is required.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    user = User(
        username=username_clean,
        password_hash=hash_password(password),
        display_name=display_name_clean or username_clean,
        currency=get_settings().default_currency,
        locale=get_settings().default_locale,
        timezone=get_settings().default_timezone,
        is_admin=is_admin,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("Username already exists.") from exc
    db.refresh(user)
    return user


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == username.strip().lower(), User.is_active.is_(True)))
    if user and verify_password(password, user.password_hash):
        return user
    return None


def _client_key(request: Request, username: str) -> tuple[str, str]:
    host = request.client.host if request.client else "unknown"
    return host, username.strip().lower()


def check_login_rate_limit(request: Request, username: str) -> None:
    settings = get_settings()
    key = _client_key(request, username)
    now = time.monotonic()
    window_started = now - settings.login_rate_limit_window_seconds
    attempts = [attempt for attempt in login_failures.get(key, []) if attempt >= window_started]
    login_failures[key] = attempts
    if len(attempts) >= settings.login_rate_limit_attempts:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many login attempts.")


def record_login_result(request: Request, username: str, success: bool) -> None:
    key = _client_key(request, username)
    if success:
        login_failures.pop(key, None)
        return
    login_failures.setdefault(key, []).append(time.monotonic())


def reset_login_throttle() -> None:
    login_failures.clear()


def login_user(request: Request, user: User) -> None:
    request.session["user_id"] = user.id


def logout_user(request: Request) -> None:
    request.session.clear()


def current_user(request: Request, db: Annotated[Session, Depends(get_db)]) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
    user = db.get(User, user_id)
    if not user or not user.is_active:
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
    return user
