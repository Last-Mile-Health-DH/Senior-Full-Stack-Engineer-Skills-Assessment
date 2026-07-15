from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
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

from app.api.v1.auth import router as auth_router
from app.api.v1.chat import router as chat_router
from app.core.errors import AppError, app_error_handler
from app.database import DATABASE_URL, get_db
from app.documents.routes import router as documents_router
from app.security.auth import _encode_jwt, verify_session_token
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
async def test_auth_session_endpoint_returns_valid_jwt() -> None:
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(auth_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/auth/session")

    assert response.status_code == 200
    token = response.json()["access_token"]
    parsed = verify_session_token(token)
    assert parsed.subject.startswith("anonymous:")


@pytest.mark.asyncio
async def test_document_routes_are_public_for_local_reviewer_use(migrated_session: AsyncSession) -> None:
    app = _documents_app(migrated_session)
    document_id = await _insert_document(migrated_session)
    expired = _expired_token()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        listed = await client.get("/api/v1/documents")
        malformed_header = await client.get("/api/v1/documents", headers={"Authorization": "Bearer nope"})
        expired_header = await client.get("/api/v1/documents", headers={"Authorization": f"Bearer {expired}"})
        fetched = await client.get(f"/api/v1/documents/{document_id}")
        deleted = await client.delete(f"/api/v1/documents/{document_id}")

    assert listed.status_code == 200
    assert malformed_header.status_code == 200
    assert expired_header.status_code == 200
    assert fetched.status_code == 200
    assert deleted.status_code == 200


@pytest.mark.asyncio
async def test_chat_anonymous_flag_controls_auth_requirement(migrated_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(chat_router)

    async def _get_db():
        yield migrated_session

    app.dependency_overrides[get_db] = _get_db

    session_id = await _insert_session(migrated_session)
    monkeypatch.setattr(settings, "anonymous_chat_allowed", True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        open_response = await client.post("/api/v1/chat", json={"session_id": str(session_id), "message": "hello"})
    assert open_response.status_code == 200

    monkeypatch.setattr(settings, "anonymous_chat_allowed", False)
    session_id_2 = await _insert_session(migrated_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        closed_response = await client.post("/api/v1/chat", json={"session_id": str(session_id_2), "message": "hello"})
    assert closed_response.status_code == 401


def _documents_app(session: AsyncSession) -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(documents_router)

    async def _get_db():
        yield session

    app.dependency_overrides[get_db] = _get_db
    return app


def _expired_token() -> str:
    now = datetime.now(UTC)
    return _encode_jwt(
        {
            "sub": "anonymous:test",
            "iat": int((now - timedelta(hours=2)).timestamp()),
            "exp": int((now - timedelta(hours=1)).timestamp()),
        }
    )


async def _insert_document(session: AsyncSession):
    row = (
        await session.execute(
            text(
                """
                INSERT INTO documents (filename, content_hash, status, page_count)
                VALUES ('auth.pdf', :hash, 'indexed', 1)
                RETURNING id
                """
            ),
            {"hash": uuid4().hex + uuid4().hex},
        )
    ).mappings().one()
    await session.commit()
    return row["id"]


async def _insert_session(session: AsyncSession):
    row = (await session.execute(text("INSERT INTO chat_sessions DEFAULT VALUES RETURNING id"))).mappings().one()
    await session.commit()
    return row["id"]
