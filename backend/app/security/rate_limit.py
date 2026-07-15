"""Postgres-backed chat rate limiting."""

from __future__ import annotations

from uuid import UUID

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import RateLimitExceededError
from app.settings import settings


def get_client_ip(request: Request) -> str:
    """Return request IP.

    BC18 deployment hardening should restrict trusted proxy handling. For now,
    this accepts the first X-Forwarded-For hop only when supplied.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    if request.client is not None:
        return request.client.host
    return "0.0.0.0"


async def enforce_chat_rate_limit(db: AsyncSession, session_id: UUID, client_ip: str) -> None:
    retry_after = await _retry_after_for_session(db, session_id)
    session_count = await _count_session_rows(db, session_id)
    if session_count > settings.rate_limit_per_session_per_hour:
        raise RateLimitExceededError("Rate limit exceeded for this chat session.", retry_after)

    ip_count = await _count_ip_rows(db, client_ip)
    if ip_count > settings.rate_limit_per_ip_per_hour:
        raise RateLimitExceededError("Rate limit exceeded for this client IP.", retry_after)


async def _count_session_rows(db: AsyncSession, session_id: UUID) -> int:
    return int(
        (
            await db.execute(
                text(
                    """
                    SELECT count(*)
                    FROM query_audit_log
                    WHERE session_id = :session_id
                      AND created_at > now() - (:window_seconds * interval '1 second')
                    """
                ),
                {"session_id": session_id, "window_seconds": settings.rate_limit_window_seconds},
            )
        ).scalar_one()
    )


async def _count_ip_rows(db: AsyncSession, client_ip: str) -> int:
    return int(
        (
            await db.execute(
                text(
                    """
                    SELECT count(*)
                    FROM query_audit_log
                    WHERE client_ip = CAST(:client_ip AS inet)
                      AND created_at > now() - (:window_seconds * interval '1 second')
                    """
                ),
                {"client_ip": client_ip, "window_seconds": settings.rate_limit_window_seconds},
            )
        ).scalar_one()
    )


async def _retry_after_for_session(db: AsyncSession, session_id: UUID) -> int:
    row = (
        await db.execute(
            text(
                """
                SELECT EXTRACT(EPOCH FROM (
                    min(created_at) + (:window_seconds * interval '1 second') - now()
                ))::int AS retry_after
                FROM query_audit_log
                WHERE session_id = :session_id
                  AND created_at > now() - (:window_seconds * interval '1 second')
                """
            ),
            {"session_id": session_id, "window_seconds": settings.rate_limit_window_seconds},
        )
    ).mappings().one()
    return max(int(row["retry_after"] or settings.rate_limit_window_seconds), 1)
