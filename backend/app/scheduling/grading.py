"""Scheduled retrospective response grading."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.judge_agent import JudgeAgent, JudgeAgentResult
from app.security.guardrails import deterministic_grounding_check
from app.settings import settings


@dataclass(slots=True)
class ResponseForGrading:
    audit_id: UUID
    query: str
    answer: str
    retrieved_chunk_ids: list[UUID]


async def nightly_grading_job(
    db: AsyncSession,
    judge_agent: JudgeAgent | None = None,
) -> None:
    """Grade ungraded responses from the recent audit window."""
    rows = await _eligible_responses(db)
    judge = judge_agent or JudgeAgent()
    sampled = 0
    for row in rows:
        source_texts = await _source_texts_for_chunks(db, row.retrieved_chunk_ids)
        grounding_passed, grounding_detail = deterministic_grounding_check(row.answer, source_texts)
        judge_result: JudgeAgentResult | None = None
        is_sampled = sampled < settings.response_grading_sample_size
        if is_sampled:
            judge_result = await judge.score_response(
                question=row.query,
                answer=row.answer,
                source_texts=source_texts,
                rubric={"rubric_version": settings.judge_rubric_version},
            )
            sampled += 1

        await db.execute(
            text(
                """
                INSERT INTO response_grade (
                    query_audit_log_id,
                    grounding_check_passed,
                    judge_score,
                    judge_rationale,
                    judge_model,
                    judge_temperature,
                    judge_rubric_version,
                    grounding_detail,
                    sampled,
                    graded_at
                )
                VALUES (
                    :query_audit_log_id,
                    :grounding_check_passed,
                    :judge_score,
                    :judge_rationale,
                    :judge_model,
                    :judge_temperature,
                    :judge_rubric_version,
                    CAST(:grounding_detail AS jsonb),
                    :sampled,
                    now()
                )
                ON CONFLICT (query_audit_log_id) DO NOTHING
                """
            ),
            {
                "query_audit_log_id": row.audit_id,
                "grounding_check_passed": grounding_passed,
                "judge_score": _judge_score(judge_result),
                "judge_rationale": judge_result.rationale if judge_result else None,
                "judge_model": judge.metadata.model if is_sampled else None,
                "judge_temperature": judge.metadata.temperature if is_sampled else None,
                "judge_rubric_version": judge.metadata.rubric_version if is_sampled else None,
                "grounding_detail": json.dumps(grounding_detail),
                "sampled": is_sampled,
            },
        )


async def config_drift_check_job(db: AsyncSession) -> None:
    """Remove stale semantic-cache rows when the embedding model changes."""
    await db.execute(
        text("DELETE FROM semantic_cache WHERE embedding_model <> :embedding_model"),
        {"embedding_model": settings.embedding_model},
    )


async def _eligible_responses(db: AsyncSession) -> list[ResponseForGrading]:
    rows = (
        await db.execute(
            text(
                """
                SELECT
                    qal.id,
                    qal.query,
                    qal.retrieved_chunk_ids,
                    cm.content AS answer
                FROM query_audit_log qal
                LEFT JOIN LATERAL (
                    SELECT content
                    FROM chat_messages cm
                    WHERE cm.session_id = qal.session_id
                      AND cm.role = 'assistant'
                      AND cm.created_at >= qal.created_at
                    ORDER BY cm.created_at ASC, cm.id ASC
                    LIMIT 1
                ) cm ON true
                WHERE qal.created_at >= now() - interval '1 day'
                  AND qal.output_filter_status IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1
                    FROM response_grade rg
                    WHERE rg.query_audit_log_id = qal.id
                  )
                ORDER BY qal.created_at ASC
                """
            )
        )
    ).mappings().all()
    return [
        ResponseForGrading(
            audit_id=row["id"],
            query=str(row["query"]),
            answer=str(row["answer"] or ""),
            retrieved_chunk_ids=list(row["retrieved_chunk_ids"] or []),
        )
        for row in rows
    ]


async def _source_texts_for_chunks(db: AsyncSession, chunk_ids: list[UUID]) -> list[str]:
    if not chunk_ids:
        return []
    rows = (
        await db.execute(
            text(
                """
                SELECT content
                FROM chunks
                WHERE id = ANY(CAST(:chunk_ids AS uuid[]))
                """
            ),
            {"chunk_ids": chunk_ids},
        )
    ).mappings().all()
    return [str(row["content"]) for row in rows]


def _judge_score(result: JudgeAgentResult | None) -> int | None:
    if result is None:
        return None
    return max(1, min(5, int(round(result.score))))
