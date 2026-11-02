"""Simple shared-password authentication with JWT cookies."""

import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, Response, HTTPException
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import UserDB, get_session

router = APIRouter(prefix="/auth", tags=["auth"])


def _get_secret() -> str:
    return os.environ["JWT_SECRET"]


def _get_password() -> str:
    return os.environ["APP_PASSWORD"]


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(
    body: LoginRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> dict:
    """Validate shared password, find-or-create user, set JWT cookie."""
    if body.password != _get_password():
        raise HTTPException(status_code=401, detail="Invalid password")

    # Find or create user by username
    user = session.exec(
        select(UserDB).where(UserDB.name == body.username)
    ).first()
    if not user:
        user = UserDB(name=body.username)
        session.add(user)
        session.commit()
        session.refresh(user)

    payload = {
        "sub": body.username,
        "user_id": user.id,
        "exp": datetime.now(timezone.utc) + timedelta(days=30),
    }
    token = jwt.encode(payload, _get_secret(), algorithm="HS256")
    is_prod = os.getenv("RAILWAY_ENVIRONMENT") is not None
    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        samesite="lax",
        secure=is_prod,
        max_age=30 * 24 * 3600,
    )
    return {"status": "ok", "user_id": user.id, "username": user.name}


@router.get("/logout")
def logout(response: Response) -> dict:
    """Clear the session cookie."""
    response.delete_cookie(key="session")
    return {"status": "ok"}


@router.get("/me")
def get_me(request: Request, session: Session = Depends(get_session)) -> dict:
    """Return the current user from the JWT cookie."""
    token = request.cookies.get("session")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, _get_secret(), algorithms=["HS256"])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    username = payload.get("sub")
    user = session.exec(select(UserDB).where(UserDB.name == username)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return {"id": user.id, "name": user.name}


def require_auth(request: Request) -> str:
    """FastAPI dependency — validates JWT cookie, returns username."""
    token = request.cookies.get("session")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, _get_secret(), algorithms=["HS256"])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    return payload.get("sub", "")
