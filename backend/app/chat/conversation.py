"""Conversation window and rolling summary helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.generation.client import GenerationClient
from app.settings import settings


@dataclass(slots=True)
class ConversationContext:
    messages: list[dict[str, str]]
    summary_created: bool
    latest_summary: str | None


async def load_conversation_context(
    db: AsyncSession,
    session_id: UUID,
    generation_client: GenerationClient,
) -> ConversationContext:
    rows = (
        await db.execute(
            text(
                """
                SELECT role, content, created_at
                FROM chat_messages
                WHERE session_id = :session_id
                ORDER BY created_at ASC, id ASC
                """
            ),
            {"session_id": session_id},
        )
    ).mappings().all()

    latest_summary_row = next((row for row in reversed(rows) if row["role"] == "system_summary"), None)
    latest_summary = str(latest_summary_row["content"]) if latest_summary_row is not None else None
    non_summary = [row for row in rows if row["role"] in ("user", "assistant")]
    window_message_count = settings.conversation_window_turns * 2
    older = non_summary[:-window_message_count] if len(non_summary) > window_message_count else []
    window = non_summary[-window_message_count:] if window_message_count else non_summary

    summary_created = False
    older_for_summary = _unsummarized_older_rows(older, latest_summary_row)
    if _token_count([dict(row) for row in older_for_summary]) > settings.conversation_summary_trigger_tokens:
        summary_input = [{"role": str(row["role"]), "content": str(row["content"])} for row in older_for_summary]
        if latest_summary:
            summary_input.insert(0, {"role": "system_summary", "content": latest_summary})
        summary_text = await generation_client.summarize(
            summary_input,
            max_tokens=settings.max_output_tokens_summary,
        )
        await db.execute(
            text(
                """
                INSERT INTO chat_messages (session_id, role, content)
                VALUES (:session_id, 'system_summary', :content)
                """
            ),
            {"session_id": session_id, "content": summary_text},
        )
        latest_summary = summary_text
        summary_created = True

    messages: list[dict[str, str]] = []
    if latest_summary:
        messages.append({"role": "system_summary", "content": latest_summary})
    messages.extend({"role": str(row["role"]), "content": str(row["content"])} for row in window)
    return ConversationContext(messages=messages, summary_created=summary_created, latest_summary=latest_summary)


def _token_count(rows: list[dict[str, object]]) -> int:
    return sum(len(str(row["content"]).split()) for row in rows)


def _unsummarized_older_rows(older: list[Any], latest_summary_row: Any | None) -> list[Any]:
    if latest_summary_row is None:
        return older
    latest_created_at = latest_summary_row["created_at"]
    return [row for row in older if row["created_at"] > latest_created_at]
