"""Agent tool tracing into the ``agent_trace_log`` table."""

from __future__ import annotations

import functools
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.settings import settings

T = TypeVar("T")


def traced(agent_name: str) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Wrap an async tool call and persist a compact trace row when a DB is supplied."""

    def decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            db = kwargs.pop("trace_db", None)
            document_id = kwargs.pop("trace_document_id", None)
            session_id = kwargs.pop("trace_session_id", None)
            query_audit_log_id = kwargs.pop("trace_query_audit_log_id", None)
            input_payload = kwargs.pop("trace_input", {})
            start = time.monotonic()
            output_payload: Any = None
            error: str | None = None
            try:
                output_payload = await fn(*args, **kwargs)
                return output_payload
            except Exception as exc:
                error = str(exc)
                raise
            finally:
                if settings.agent_trace_logging_enabled and db is not None:
                    await _write_trace_row(
                        db=db,
                        agent_name=agent_name,
                        tool_name=fn.__name__,
                        input_payload=_redact(input_payload),
                        output_payload=_redact(output_payload) if error is None else None,
                        session_id=session_id,
                        query_audit_log_id=query_audit_log_id,
                        document_id=document_id,
                        duration_ms=int((time.monotonic() - start) * 1000),
                        error=error,
                    )

        return wrapper

    return decorator


async def _write_trace_row(
    db: AsyncSession,
    agent_name: str,
    tool_name: str,
    input_payload: dict[str, Any],
    output_payload: Any,
    session_id: Any,
    query_audit_log_id: Any,
    document_id: Any,
    duration_ms: int,
    error: str | None,
) -> None:
    await db.execute(
        text(
            """
            INSERT INTO agent_trace_log (
                agent_name,
                tool_name,
                input,
                output,
                session_id,
                query_audit_log_id,
                document_id,
                duration_ms,
                error
            )
            VALUES (
                :agent_name,
                :tool_name,
                CAST(:input AS jsonb),
                CAST(:output AS jsonb),
                :session_id,
                :query_audit_log_id,
                :document_id,
                :duration_ms,
                :error
            )
            """
        ),
        {
            "agent_name": agent_name,
            "tool_name": tool_name,
            "input": _json_literal(input_payload),
            "output": _json_literal(output_payload) if output_payload is not None else None,
            "session_id": session_id,
            "query_audit_log_id": query_audit_log_id,
            "document_id": document_id,
            "duration_ms": duration_ms,
            "error": error,
        },
    )


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        return value if len(value) <= 240 else f"{value[:240]}...<redacted>"
    if isinstance(value, list):
        return [_redact(item) for item in value[:20]]
    if isinstance(value, tuple):
        return [_redact(item) for item in value[:20]]
    if isinstance(value, dict):
        return {str(key): _redact(item) for key, item in value.items()}
    if hasattr(value, "model_dump"):
        return _redact(value.model_dump())
    return value


def _json_literal(value: Any) -> str:
    import json

    return json.dumps(value, default=str)
