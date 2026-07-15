"""Lightweight HS256 JWT-compatible session tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import Depends, Header

from app.core.errors import UnauthorizedError
from app.settings import settings


@dataclass(slots=True)
class AuthSession:
    subject: str
    expires_at: int


def issue_session_token() -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": f"anonymous:{uuid4()}",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.session_token_expiry_minutes)).timestamp()),
    }
    return _encode_jwt(payload)


async def require_auth(authorization: str | None = Header(default=None)) -> AuthSession:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise UnauthorizedError("A valid bearer token is required.")
    token = authorization.split(" ", 1)[1].strip()
    return verify_session_token(token)


def verify_session_token(token: str) -> AuthSession:
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        expected = _sign(signing_input)
        actual = _b64decode(signature_b64)
        if not hmac.compare_digest(expected, actual):
            raise UnauthorizedError("Session token signature is invalid.")
        payload = json.loads(_b64decode(payload_b64))
        exp = int(payload["exp"])
        if exp < int(datetime.now(UTC).timestamp()):
            raise UnauthorizedError("Session token has expired.")
        subject = str(payload["sub"])
    except UnauthorizedError:
        raise
    except Exception as exc:
        raise UnauthorizedError("Session token is malformed.") from exc
    return AuthSession(subject=subject, expires_at=exp)


def _encode_jwt(payload: dict[str, object]) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = _b64encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature_b64 = _b64encode(_sign(f"{header_b64}.{payload_b64}".encode("ascii")))
    return f"{header_b64}.{payload_b64}.{signature_b64}"


def _sign(signing_input: bytes) -> bytes:
    return hmac.new(settings.jwt_secret.encode("utf-8"), signing_input, hashlib.sha256).digest()


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padded = value + ("=" * (-len(value) % 4))
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def auth_dependency() -> Depends:
    return Depends(require_auth)
