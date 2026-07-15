"""End-to-end audit trail.

One question must be replayable from one key. `agent_trace_log` recorded WHAT ran but
never WHY it ran that way — the model the router picked, the strategy the chunker chose,
how confident retrieval was. Those are the rows that answer "why was this answer weak?"
after the fact, and they are what this file pins.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents.orchestrator import RetrievalUnavailableError
from app.api.v1.chat import router as chat_router
from app.core.errors import AppError, app_error_handler
from app.database import DATABASE_URL, get_db
from app.generation.client import GenerationResult
from app.retrieval.models import RetrievalAgentResult, RetrievalCandidate

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DIMENSIONS = 1536


class StaticEmbeddingClient:
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] + [0.0] * (DIMENSIONS - 1) for _ in texts]


class FakeGeneration:
    async def generate(self, payload, max_tokens: int) -> GenerationResult:
        return GenerationResult(
            "Malaria treatment includes clinic follow up.[cite:1]", payload.model, 10, 6, 0.0
        )

    async def summarize(self, messages: list[dict[str, str]], max_tokens: int) -> str:
        return "summary"


class FakeRetrieval:
    def __init__(self, candidate: RetrievalCandidate, score: float) -> None:
        self.candidate = candidate
        self.score = score

    async def run(self, **kwargs):
        return RetrievalAgentResult(
            chunks=[self.candidate],
            page_images=[],
            retrieval_mode="hybrid",
            top_relevance_score=self.score,
        )


@pytest_asyncio.fixture()
async def db_session():
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = create_async_engine(DATABASE_URL, echo=False)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()
        command.downgrade(config, "base")


@pytest.mark.asyncio
async def test_one_question_replays_its_whole_chain_from_one_key(db_session) -> None:
    document_id = await _indexed_document(db_session)
    candidate = RetrievalCandidate(
        chunk_id=uuid4(),
        document_id=document_id,
        document_filename="source.pdf",
        document_status="indexed",
        content="malaria treatment includes clinic follow up",
        page_number=1,
    )
    app = _app(db_session, FakeRetrieval(candidate, score=0.87), FakeGeneration())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/chat", json={"message": "malaria"})

    payload = response.json()
    audit_id = UUID(payload["query_audit_log_id"])
    session_id = UUID(payload["session_id"])

    rows = (
        await db_session.execute(
            text(
                """
                SELECT agent_id, tool_name, event_type, score, session_id, output
                FROM agent_trace_log
                WHERE query_audit_log_id = :audit_id
                ORDER BY created_at
                """
            ),
            {"audit_id": audit_id},
        )
    ).mappings().all()

    by_agent = {row["agent_id"]: row for row in rows}

    # The router's choice is recorded: which model answered, and on what basis.
    router = by_agent["model_router"]
    assert router["event_type"] == "decision"
    assert router["tool_name"] == "generation_model_selected"
    assert router["output"]["model"]
    assert router["output"]["reason"]

    # Retrieval's confidence is recorded as a score, so answer quality is queryable.
    retrieval = by_agent["retrieval_agent"]
    assert retrieval["event_type"] == "score"
    assert retrieval["score"] == pytest.approx(0.87)
    assert retrieval["output"]["retrieval_mode"] == "hybrid"
    assert retrieval["output"]["chunks_retrieved"] == 1

    # Every row in the chain is tied to the same session, so a session replays too.
    assert {row["session_id"] for row in rows} == {session_id}


@pytest.mark.asyncio
async def test_the_degraded_path_records_that_no_model_was_configured(
    db_session, monkeypatch
) -> None:
    """An answer produced without a model must be identifiable in the audit forever after."""
    # Simulate an unconfigured deployment. The container this runs in may have a real key.
    for name in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "VOYAGE_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    document_id = await _indexed_document(db_session)
    candidate = RetrievalCandidate(
        chunk_id=uuid4(),
        document_id=document_id,
        document_filename="source.pdf",
        document_status="indexed",
        content="malaria treatment includes clinic follow up",
        page_number=1,
    )
    app = _app(db_session, FakeRetrieval(candidate, score=0.5), FakeGeneration())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/chat", json={"message": "malaria"})

    audit_id = UUID(response.json()["query_audit_log_id"])
    row = (
        await db_session.execute(
            text(
                """
                SELECT output FROM agent_trace_log
                WHERE query_audit_log_id = :audit_id AND agent_id = 'model_router'
                """
            ),
            {"audit_id": audit_id},
        )
    ).mappings().one()

    # In the test environment no provider key is configured, so the router must say so.
    assert row["output"]["model"] == "deterministic-fallback"
    assert "no provider key" in row["output"]["reason"]

    status = response.json()["model_status"]
    assert status["mode"] == "degraded"
    assert status["notice"]


def _app(session: AsyncSession, retrieval, generation) -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(chat_router)
    app.state.embedding_client = StaticEmbeddingClient()
    app.state.retrieval_agent = retrieval
    app.state.generation_client = generation
    factory = async_sessionmaker(bind=session.bind, class_=AsyncSession, expire_on_commit=False)

    async def _get_db():
        async with factory() as request_session:
            yield request_session

    app.dependency_overrides[get_db] = _get_db
    return app


async def _indexed_document(session: AsyncSession):
    row = (
        await session.execute(
            text(
                """
                INSERT INTO documents (filename, content_hash, status, page_count)
                VALUES ('source.pdf', :hash, 'indexed', 1) RETURNING id
                """
            ),
            {"hash": uuid4().hex + uuid4().hex},
        )
    ).mappings().one()
    await session.commit()
    return row["id"]


@pytest.mark.asyncio
async def test_a_failed_trace_write_does_not_poison_the_caller_transaction(db_session) -> None:
    """record_decision runs inside the caller's transaction and is best-effort.

    If its INSERT fails (a deadlock under concurrent ingestion, say), catching the Python
    exception is not enough — the failed statement aborts the whole outer transaction, and
    the caller's next statement dies with InFailedSQLTransactionError. The savepoint scopes
    the failure so the outer transaction survives. This test forces the insert to fail and
    asserts the session can still do real work afterwards.
    """
    from app.agents.tracing import record_decision

    # A document_id that violates the FK forces the trace INSERT to fail.
    await record_decision(
        db_session,
        agent_id="ingestion_agent",
        decision="chunk_strategy_selected",
        detail={"chunk_strategy": "fixed_size"},
        document_id=uuid4(),  # no such document -> FK violation inside the savepoint
    )

    # The outer transaction must still be usable. Before the savepoint fix this raised
    # InFailedSQLTransactionError.
    ok = (await db_session.execute(text("SELECT 1"))).scalar_one()
    assert ok == 1

    # And a real insert still commits.
    document_id = await _indexed_document(db_session)
    count = (
        await db_session.execute(
            text("SELECT count(*) FROM documents WHERE id = :id"), {"id": document_id}
        )
    ).scalar_one()
    assert count == 1
