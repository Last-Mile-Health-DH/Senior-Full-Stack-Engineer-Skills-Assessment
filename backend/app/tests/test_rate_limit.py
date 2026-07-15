from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1.chat import router as chat_router
from app.cache.exact import write_exact_cache
from app.core.errors import AppError, app_error_handler
from app.database import DATABASE_URL, get_db
from app.settings import settings

BACKEND_ROOT = Path(__file__).resolve().parents[2]


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
async def test_per_session_limit_returns_429_with_retry_after(migrated_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_per_session_per_hour", 1)
    monkeypatch.setattr(settings, "rate_limit_per_ip_per_hour", 100)
    app = _chat_app(migrated_session)
    session_id = await _insert_session(migrated_session)
    await _insert_audit(migrated_session, session_id, "203.0.113.1")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat",
            headers={"X-Forwarded-For": "203.0.113.1"},
            json={"session_id": str(session_id), "message": "limit me"},
        )

    assert response.status_code == 429
    assert response.headers["Retry-After"]
    assert response.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"


@pytest.mark.asyncio
async def test_different_session_same_ip_unaffected_until_ip_ceiling(migrated_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_per_session_per_hour", 1)
    monkeypatch.setattr(settings, "rate_limit_per_ip_per_hour", 3)
    app = _chat_app(migrated_session)
    first_session = await _insert_session(migrated_session)
    second_session = await _insert_session(migrated_session)
    await _insert_audit(migrated_session, first_session, "203.0.113.2")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat",
            headers={"X-Forwarded-For": "203.0.113.2"},
            json={"session_id": str(second_session), "message": "hello"},
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_per_ip_limit_returns_429_across_sessions(migrated_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_per_session_per_hour", 100)
    monkeypatch.setattr(settings, "rate_limit_per_ip_per_hour", 1)
    app = _chat_app(migrated_session)
    first_session = await _insert_session(migrated_session)
    second_session = await _insert_session(migrated_session)
    await _insert_audit(migrated_session, first_session, "203.0.113.3")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat",
            headers={"X-Forwarded-For": "203.0.113.3"},
            json={"session_id": str(second_session), "message": "hello"},
        )

    assert response.status_code == 429


@pytest.mark.asyncio
async def test_rate_limiting_happens_before_cache_lookup(migrated_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_per_session_per_hour", 0)
    monkeypatch.setattr(settings, "rate_limit_per_ip_per_hour", 100)
    document_id = await _insert_document(migrated_session)
    session_id = await _insert_session(migrated_session)
    await write_exact_cache(migrated_session, "cached", "cached answer", [document_id], eligible=True)
    await migrated_session.commit()
    app = _chat_app(migrated_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/chat", json={"session_id": str(session_id), "message": "cached"})

    assert response.status_code == 429


def _chat_app(session: AsyncSession) -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(chat_router)

    async def _get_db():
        yield session

    app.dependency_overrides[get_db] = _get_db
    return app


async def _insert_session(session: AsyncSession):
    row = (await session.execute(text("INSERT INTO chat_sessions DEFAULT VALUES RETURNING id"))).mappings().one()
    await session.commit()
    return row["id"]


async def _insert_audit(session: AsyncSession, session_id, ip: str) -> None:
    await session.execute(
        text(
            """
            INSERT INTO query_audit_log (session_id, query, client_ip, latency_ms)
            VALUES (:session_id, 'seed', CAST(:ip AS inet), 1)
            """
        ),
        {"session_id": session_id, "ip": ip},
    )
    await session.commit()


async def _insert_document(session: AsyncSession):
    row = (
        await session.execute(
            text(
                """
                INSERT INTO documents (filename, content_hash, status, page_count)
                VALUES ('rate.pdf', :hash, 'indexed', 1)
                RETURNING id
                """
            ),
            {"hash": uuid4().hex + uuid4().hex},
        )
    ).mappings().one()
    await session.commit()
    return row["id"]
