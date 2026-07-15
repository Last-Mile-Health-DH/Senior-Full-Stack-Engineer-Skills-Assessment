from __future__ import annotations

import asyncio
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
from app.cache.exact import lookup_exact_cache, write_exact_cache
from app.cache.semantic import write_semantic_cache
from app.chat.response_presenter import (
    DOCUMENT_PREPARING_MESSAGE,
    NO_ANSWER_MESSAGE,
    RETRIEVAL_UNAVAILABLE_MESSAGE,
    UPLOAD_FIRST_MESSAGE,
)
from app.core.errors import AppError, app_error_handler
from app.database import DATABASE_URL, get_db
from app.generation.client import GenerationResult
from app.retrieval.models import RetrievalAgentResult, RetrievalCandidate
from app.settings import settings

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DIMENSIONS = 1536


class StaticEmbeddingClient:
    def __init__(self) -> None:
        self.calls = 0

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [[1.0] + [0.0] * (DIMENSIONS - 1) for _ in texts]


class FakeGenerationClient:
    # The default answer honors the `[cite:n]` contract the presenter enforces: an
    # answer with no surviving citation is converted to the concise no-answer.
    def __init__(
        self,
        answer: str = "Malaria treatment includes clinic follow up.[cite:1]",
        delay: float = 0.0,
    ) -> None:
        self.answer = answer
        self.delay = delay
        self.calls = 0
        self.summary_calls = 0

    async def generate(self, payload, max_tokens: int) -> GenerationResult:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return GenerationResult(self.answer, payload.model, 10, 6, 0.0)

    async def summarize(self, messages: list[dict[str, str]], max_tokens: int) -> str:
        self.summary_calls += 1
        return "latest generated summary"


class FakeRetrievalAgent:
    def __init__(self, candidate: RetrievalCandidate | None, fail: bool = False) -> None:
        self.candidate = candidate
        self.fail = fail
        self.calls = 0

    async def run(self, **kwargs):
        self.calls += 1
        if self.fail:
            raise RetrievalUnavailableError("forced")
        return RetrievalAgentResult(
            chunks=[self.candidate] if self.candidate else [],
            page_images=[],
            retrieval_mode="deterministic",
            top_relevance_score=0.99,
        )


@pytest_asyncio.fixture()
async def migrated_session():
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = create_async_engine(DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with session_factory() as session:
            yield session
    finally:
        await engine.dispose()
        command.downgrade(config, "base")


@pytest.mark.asyncio
async def test_duplicate_chat_request_returns_same_result_without_second_generation(migrated_session: AsyncSession) -> None:
    document_id = await _insert_indexed_document(migrated_session)
    session_id = await _insert_session(migrated_session)
    candidate = _candidate(document_id)
    generation = FakeGenerationClient()
    retrieval = FakeRetrievalAgent(candidate)
    app = _chat_app(migrated_session, retrieval, generation)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/api/v1/chat", json={"session_id": str(session_id), "message": "malaria"})
        second = await client.post("/api/v1/chat", json={"session_id": str(session_id), "message": "malaria"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["answer"] == second.json()["answer"]
    assert generation.calls == 1
    assert retrieval.calls == 1


@pytest.mark.asyncio
async def test_concurrent_duplicate_requests_only_generate_once(migrated_session: AsyncSession) -> None:
    document_id = await _insert_indexed_document(migrated_session)
    session_id = await _insert_session(migrated_session)
    generation = FakeGenerationClient(delay=0.2)
    retrieval = FakeRetrievalAgent(_candidate(document_id))
    app = _chat_app(migrated_session, retrieval, generation)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        responses = await asyncio.gather(
            client.post("/api/v1/chat", json={"session_id": str(session_id), "message": "malaria"}),
            client.post("/api/v1/chat", json={"session_id": str(session_id), "message": "malaria"}),
        )

    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json()["answer"] == responses[1].json()["answer"]
    assert generation.calls == 1
    assert retrieval.calls == 1


@pytest.mark.asyncio
async def test_conversation_summary_triggers_only_over_threshold(migrated_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "conversation_window_turns", 1)
    monkeypatch.setattr(settings, "conversation_summary_trigger_tokens", 5)
    session_id = await _insert_session(migrated_session)
    generation = FakeGenerationClient()

    await _insert_message(migrated_session, session_id, "user", "one two three")
    await _insert_message(migrated_session, session_id, "assistant", "four five six")
    from app.chat.conversation import load_conversation_context

    before = await load_conversation_context(migrated_session, session_id, generation)
    assert before.summary_created is False
    assert generation.summary_calls == 0

    await _insert_message(migrated_session, session_id, "user", "six")
    await _insert_message(migrated_session, session_id, "assistant", "seven")
    after = await load_conversation_context(migrated_session, session_id, generation)
    assert after.summary_created is True
    assert generation.summary_calls == 1


@pytest.mark.asyncio
async def test_only_most_recent_system_summary_is_read(migrated_session: AsyncSession) -> None:
    session_id = await _insert_session(migrated_session)
    await _insert_message(migrated_session, session_id, "system_summary", "old summary")
    await _insert_message(migrated_session, session_id, "system_summary", "new summary")
    from app.chat.conversation import load_conversation_context

    context = await load_conversation_context(migrated_session, session_id, FakeGenerationClient())
    summaries = [message["content"] for message in context.messages if message["role"] == "system_summary"]
    assert summaries == ["new summary"]


@pytest.mark.asyncio
async def test_exact_cache_hit_skips_retrieval_and_generation(migrated_session: AsyncSession) -> None:
    document_id = await _insert_indexed_document(migrated_session)
    session_id = await _insert_session(migrated_session)
    await write_exact_cache(migrated_session, "malaria", "cached answer", [document_id], eligible=True)
    await migrated_session.commit()
    generation = FakeGenerationClient()
    retrieval = FakeRetrievalAgent(_candidate(document_id))
    app = _chat_app(migrated_session, retrieval, generation)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/chat", json={"session_id": str(session_id), "message": "malaria"})

    assert response.json()["cache_status"] == "exact_hit"
    assert response.json()["answer"] == "cached answer"
    assert retrieval.calls == 0
    assert generation.calls == 0


@pytest.mark.asyncio
async def test_semantic_cache_hit_skips_retrieval_and_generation(migrated_session: AsyncSession) -> None:
    document_id = await _insert_indexed_document(migrated_session)
    session_id = await _insert_session(migrated_session)
    embedder = StaticEmbeddingClient()
    await write_semantic_cache(
        migrated_session,
        "near malaria",
        "semantic cached answer",
        [document_id],
        eligible=True,
        embedding_client=embedder,
    )
    await migrated_session.commit()
    generation = FakeGenerationClient()
    retrieval = FakeRetrievalAgent(_candidate(document_id))
    app = _chat_app(migrated_session, retrieval, generation)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/chat", json={"session_id": str(session_id), "message": "malaria"})

    assert response.json()["cache_status"] == "semantic_hit"
    assert response.json()["answer"] == "semantic cached answer"
    assert retrieval.calls == 0
    assert generation.calls == 0


@pytest.mark.asyncio
async def test_empty_corpus_returns_upload_first_without_retrieval(migrated_session: AsyncSession) -> None:
    session_id = await _insert_session(migrated_session)
    generation = FakeGenerationClient()
    retrieval = FakeRetrievalAgent(None)
    app = _chat_app(migrated_session, retrieval, generation)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/chat", json={"session_id": str(session_id), "message": "malaria"})

    assert response.json()["answer"] == UPLOAD_FIRST_MESSAGE
    assert retrieval.calls == 0
    assert generation.calls == 0


@pytest.mark.asyncio
async def test_document_still_processing_is_not_told_to_upload_first(migrated_session: AsyncSession) -> None:
    """A PDF that is still being prepared is not the same as having no PDF at all."""
    await _insert_processing_document(migrated_session)
    session_id = await _insert_session(migrated_session)
    generation = FakeGenerationClient()
    retrieval = FakeRetrievalAgent(None)
    app = _chat_app(migrated_session, retrieval, generation)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/chat", json={"session_id": str(session_id), "message": "malaria"})

    assert response.json()["answer"] == DOCUMENT_PREPARING_MESSAGE
    assert response.json()["answer"] != UPLOAD_FIRST_MESSAGE
    assert retrieval.calls == 0
    assert generation.calls == 0


@pytest.mark.asyncio
async def test_retrieval_failure_does_not_generate(migrated_session: AsyncSession) -> None:
    document_id = await _insert_indexed_document(migrated_session)
    session_id = await _insert_session(migrated_session)
    generation = FakeGenerationClient()
    retrieval = FakeRetrievalAgent(_candidate(document_id), fail=True)
    app = _chat_app(migrated_session, retrieval, generation)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/chat", json={"session_id": str(session_id), "message": "malaria"})

    # "Cannot search right now" must stay distinguishable from "not in the corpus",
    # without exposing why retrieval failed.
    assert response.json()["answer"] == RETRIEVAL_UNAVAILABLE_MESSAGE
    assert response.json()["answer"] != NO_ANSWER_MESSAGE
    assert retrieval.calls == 1
    assert generation.calls == 0


@pytest.mark.asyncio
async def test_query_audit_finalized_and_source_chunks_persist(migrated_session: AsyncSession) -> None:
    document_id = await _insert_indexed_document(migrated_session)
    session_id = await _insert_session(migrated_session)
    candidate = _candidate(document_id)
    app = _chat_app(migrated_session, FakeRetrievalAgent(candidate), FakeGenerationClient())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/chat", json={"session_id": str(session_id), "message": "malaria"})

    payload = response.json()
    assert payload["answer"] == "Malaria treatment includes clinic follow up.¹"
    assert payload["citations"] == [
        {
            "number": 1,
            "chunk_id": str(candidate.chunk_id),
            "document_id": str(candidate.document_id),
            "document_title": "Source",
            "document_filename": "source.pdf",
            "page_number": 1,
            "section_path": None,
            "snippet": "malaria treatment includes clinic follow up and artemisinin combination therapy",
            "reference": "1. Source, p. 1.",
        }
    ]
    audit = (
        await migrated_session.execute(
            text(
                """
                SELECT cache_status, retrieved_chunk_ids, reranked, retrieval_mode, generation_model,
                       grounded, output_filter_status, latency_ms, token_input, token_output, cost_usd
                FROM query_audit_log
                WHERE id = :id
                """
            ),
            {"id": UUID(payload["query_audit_log_id"])},
        )
    ).mappings().one()
    assistant = (
        await migrated_session.execute(
            text("SELECT source_chunk_ids FROM chat_messages WHERE session_id = :session_id AND role = 'assistant'"),
            {"session_id": session_id},
        )
    ).mappings().one()
    assert audit["cache_status"] == "miss"
    assert audit["retrieved_chunk_ids"] == [candidate.chunk_id]
    assert audit["reranked"] is True
    assert audit["retrieval_mode"] == "deterministic"
    assert audit["generation_model"] == settings.generation_model_primary
    assert audit["grounded"] is True
    assert audit["output_filter_status"] == "passed"
    assert audit["latency_ms"] is not None
    assert audit["token_input"] == 10
    assert audit["token_output"] == 6
    # Do not hardcode a cost: the router chooses the model, so a literal here silently
    # becomes wrong the moment the cheapest configured provider changes. Assert the
    # BEHAVIOR instead — that the cost was derived from the model that actually ran.
    from app.core.cost import compute_cost

    from decimal import ROUND_HALF_UP, Decimal

    expected_cost = compute_cost(
        audit["generation_model"], audit["token_input"], audit["token_output"]
    )
    # `cost_usd` is NUMERIC with 6 decimal places, so the stored value is the computed cost
    # rounded to the column's scale. Compare at that scale rather than against the raw
    # float, or a cheap model's per-request cost fails the assertion purely on precision.
    quantized = Decimal(expected_cost).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    assert audit["cost_usd"] == quantized
    assert audit["cost_usd"] >= 0
    assert assistant["source_chunk_ids"] == [candidate.chunk_id]


@pytest.mark.asyncio
async def test_uncited_factual_answer_is_converted_to_safe_no_answer(migrated_session: AsyncSession) -> None:
    document_id = await _insert_indexed_document(migrated_session)
    session_id = await _insert_session(migrated_session)
    # Grounded wording, but the model never cited a source block.
    generation = FakeGenerationClient(answer="Malaria treatment includes clinic follow up.")
    app = _chat_app(migrated_session, FakeRetrievalAgent(_candidate(document_id)), generation)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/chat", json={"session_id": str(session_id), "message": "malaria"})

    payload = response.json()
    assert payload["answer"] == NO_ANSWER_MESSAGE
    assert payload["citations"] == []
    assert payload["output_filter_status"] == "filtered"
    assert payload["output_filter_reason"] == "missing_citations"


@pytest.mark.asyncio
async def test_no_answer_response_carries_no_citations(migrated_session: AsyncSession) -> None:
    document_id = await _insert_indexed_document(migrated_session)
    session_id = await _insert_session(migrated_session)
    generation = FakeGenerationClient(answer="I could not find that in the uploaded documents.")
    app = _chat_app(migrated_session, FakeRetrievalAgent(_candidate(document_id)), generation)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/chat", json={"session_id": str(session_id), "message": "rabies"})

    payload = response.json()
    assert payload["answer"] == NO_ANSWER_MESSAGE
    assert payload["citations"] == []


@pytest.mark.asyncio
async def test_answer_never_opens_with_a_document_name(migrated_session: AsyncSession) -> None:
    document_id = await _insert_indexed_document(migrated_session)
    session_id = await _insert_session(migrated_session)
    generation = FakeGenerationClient(
        answer="source.pdf: Malaria treatment includes clinic follow up.[cite:1]"
    )
    app = _chat_app(migrated_session, FakeRetrievalAgent(_candidate(document_id)), generation)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/chat", json={"session_id": str(session_id), "message": "malaria"})

    answer = response.json()["answer"]
    assert answer == "Malaria treatment includes clinic follow up.¹"
    assert not answer.lower().startswith("source.pdf")


@pytest.mark.asyncio
async def test_uncited_answer_is_not_cached(migrated_session: AsyncSession) -> None:
    document_id = await _insert_indexed_document(migrated_session)
    session_id = await _insert_session(migrated_session)
    generation = FakeGenerationClient(answer="Malaria treatment includes clinic follow up.")
    app = _chat_app(migrated_session, FakeRetrievalAgent(_candidate(document_id)), generation)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/api/v1/chat", json={"session_id": str(session_id), "message": "malaria"})

    assert await lookup_exact_cache(migrated_session, "malaria") is None


@pytest.mark.asyncio
async def test_cache_hit_rebuilds_the_same_reference_list(migrated_session: AsyncSession) -> None:
    """A cached answer keeps its superscripts, so it must keep its references too."""
    document_id = await _insert_indexed_document(migrated_session)
    chunk_id = await _insert_chunk(migrated_session, document_id)
    session_id = await _insert_session(migrated_session)
    candidate = _candidate(document_id).model_copy(update={"chunk_id": chunk_id})
    generation = FakeGenerationClient()
    app = _chat_app(migrated_session, FakeRetrievalAgent(candidate), generation)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/api/v1/chat", json={"session_id": str(session_id), "message": "malaria"})
        second = await client.post(
            "/api/v1/chat",
            json={"session_id": str(await _insert_session(migrated_session)), "message": "malaria"},
        )

    assert second.json()["cache_status"] == "exact_hit"
    assert second.json()["answer"] == first.json()["answer"]
    assert "¹" in second.json()["answer"]
    assert [citation["reference"] for citation in second.json()["citations"]] == [
        citation["reference"] for citation in first.json()["citations"]
    ]
    assert generation.calls == 1


def _chat_app(session: AsyncSession, retrieval: FakeRetrievalAgent, generation: FakeGenerationClient) -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(chat_router)
    app.state.embedding_client = StaticEmbeddingClient()
    app.state.retrieval_agent = retrieval
    app.state.generation_client = generation
    session_factory = async_sessionmaker(bind=session.bind, class_=AsyncSession, expire_on_commit=False)

    async def _get_db():
        async with session_factory() as request_session:
            yield request_session

    app.dependency_overrides[get_db] = _get_db
    return app


def _candidate(document_id) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=uuid4(),
        document_id=document_id,
        document_filename="source.pdf",
        document_status="indexed",
        content="malaria treatment includes clinic follow up and artemisinin combination therapy",
        page_number=1,
    )


async def _insert_indexed_document(session: AsyncSession):
    row = (
        await session.execute(
            text(
                """
                INSERT INTO documents (filename, content_hash, status, page_count)
                VALUES ('source.pdf', :hash, 'indexed', 1)
                RETURNING id
                """
            ),
            {"hash": uuid4().hex + uuid4().hex},
        )
    ).mappings().one()
    await session.commit()
    return row["id"]


async def _insert_processing_document(session: AsyncSession):
    row = (
        await session.execute(
            text(
                """
                INSERT INTO documents (filename, content_hash, status)
                VALUES ('pending.pdf', :hash, 'processing')
                RETURNING id
                """
            ),
            {"hash": uuid4().hex + uuid4().hex},
        )
    ).mappings().one()
    await session.commit()
    return row["id"]


async def _insert_chunk(session: AsyncSession, document_id):
    """A real chunk row is needed wherever citations are rebuilt from the database."""
    row = (
        await session.execute(
            text(
                """
                INSERT INTO chunks (
                    document_id, chunk_index, content, content_hash,
                    page_number, embedding, embedding_model
                )
                VALUES (
                    :document_id, 0,
                    'malaria treatment includes clinic follow up and artemisinin combination therapy',
                    :content_hash,
                    1,
                    CAST(:embedding AS vector),
                    'text-embedding-3-small'
                )
                RETURNING id
                """
            ),
            {
                "document_id": document_id,
                "content_hash": uuid4().hex + uuid4().hex,
                "embedding": "[" + ",".join(["0.0"] * DIMENSIONS) + "]",
            },
        )
    ).mappings().one()
    await session.commit()
    return row["id"]


async def _insert_session(session: AsyncSession):
    row = (await session.execute(text("INSERT INTO chat_sessions DEFAULT VALUES RETURNING id"))).mappings().one()
    await session.commit()
    return row["id"]


async def _insert_message(session: AsyncSession, session_id, role: str, content: str) -> None:
    await session.execute(
        text("INSERT INTO chat_messages (session_id, role, content) VALUES (:session_id, :role, :content)"),
        {"session_id": session_id, "role": role, "content": content},
    )
    await session.commit()
