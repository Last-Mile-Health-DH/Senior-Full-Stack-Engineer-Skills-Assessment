"""BC15 auth endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.security.auth import issue_session_token

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/session")
async def create_session() -> dict[str, object]:
    token = issue_session_token()
    return {"access_token": token, "token_type": "bearer"}
