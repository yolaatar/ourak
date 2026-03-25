"""Simple shared-password authentication with JWT cookies."""

import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request, Response, HTTPException
from jose import JWTError, jwt
from pydantic import BaseModel

router = APIRouter(prefix="/auth", tags=["auth"])


def _get_secret() -> str:
    return os.environ["JWT_SECRET"]


def _get_password() -> str:
    return os.environ["APP_PASSWORD"]


class LoginRequest(BaseModel):
    password: str


@router.post("/login")
def login(body: LoginRequest, response: Response) -> dict:
    """Validate shared password and set a signed JWT cookie."""
    if body.password != _get_password():
        raise HTTPException(status_code=401, detail="Invalid password")

    payload = {
        "sub": "user",
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
    return {"status": "ok"}


@router.get("/logout")
def logout(response: Response) -> dict:
    """Clear the session cookie."""
    response.delete_cookie(key="session")
    return {"status": "ok"}


def require_auth(request: Request) -> None:
    """FastAPI dependency — validates JWT cookie, raises 401 if invalid."""
    token = request.cookies.get("session")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        jwt.decode(token, _get_secret(), algorithms=["HS256"])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
