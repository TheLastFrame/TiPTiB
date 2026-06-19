from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from passlib.context import CryptContext
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


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
    user = User(
        username=username.strip().lower(),
        password_hash=hash_password(password),
        display_name=(display_name or username).strip(),
        is_admin=is_admin,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == username.strip().lower(), User.is_active.is_(True)))
    if user and verify_password(password, user.password_hash):
        return user
    return None


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
