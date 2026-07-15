"""Agent tool tracing into the ``agent_trace_log`` table."""

from __future__ import annotations

import json
import functools
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.settings import settings

logger = logging.getLogger(__name__)

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


# ---------------------------------------------------------------------------- decisions

async def record_decision(
    db: AsyncSession | None,
    *,
    agent_id: str,
    decision: str,
    detail: dict[str, Any],
    session_id: Any = None,
    query_audit_log_id: Any = None,
    document_id: Any = None,
    score: float | None = None,
) -> None:
    """Persist a decision or a score, not just a tool call.

    `agent_trace_log` recorded WHAT ran but never WHY it ran that way. The choices that
    actually determine an answer — which model the router picked and on what basis, which
    chunking strategy a document got, how confident the reranker was — were invisible to an
    audit. Recording them against the same `query_audit_log_id` as the tool calls means one
    question's entire chain can be replayed end to end from a single key.

    Tracing must never take down a request: a failure to write an audit row is logged and
    swallowed, because losing observability is strictly better than losing the answer.

    The write runs inside a SAVEPOINT, and that is load-bearing, not defensive dressing.
    This runs inside the caller's transaction (the ingestion or chat transaction). When
    several documents ingest at once, concurrent inserts into `agent_trace_log` can
    deadlock — Postgres kills one. Catching the Python exception is not enough: the killed
    statement leaves the *whole outer transaction* aborted, so the caller's very next
    statement fails with InFailedSQLTransactionError and the real work is lost to a dropped
    audit row. `begin_nested()` scopes the failure to the savepoint, which rolls back on its
    own, leaving the outer transaction healthy to finish the ingestion.
    """
    if not settings.agent_trace_logging_enabled or db is None:
        return
    try:
        async with db.begin_nested():
            await db.execute(
                text(
                    """
                    INSERT INTO agent_trace_log (
                        agent_name, agent_id, tool_name, event_type,
                        input, output, score,
                        session_id, query_audit_log_id, document_id
                    )
                    VALUES (
                        :agent_name, :agent_id, :decision, :event_type,
                        CAST(:input AS jsonb), CAST(:output AS jsonb), :score,
                        :session_id, :query_audit_log_id, :document_id
                    )
                    """
                ),
                {
                    "agent_name": agent_id,
                    "agent_id": agent_id,
                    "decision": decision,
                    "event_type": "score" if score is not None else "decision",
                    "input": json.dumps({"decision": decision}),
                    "output": json.dumps(_redact(detail)),
                    "score": score,
                    "session_id": session_id,
                    "query_audit_log_id": query_audit_log_id,
                    "document_id": document_id,
                },
            )
    except Exception as exc:  # pragma: no cover - observability must not break the request
        logger.warning("trace.decision_write_failed agent_id=%s error=%s", agent_id, exc)
