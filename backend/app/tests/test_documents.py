import os
import io
import hashlib
from pathlib import Path
import pytest
import pytest_asyncio
import pdfplumber
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import UUID

from alembic import command
from alembic.config import Config
from fastapi import FastAPI, status
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select

from app.database import get_db, DATABASE_URL
from app.documents.routes import router
from app.models import Base, Document

# Resolve directories relative to backend root
BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Resolve upload storage path relative to the app/ directory
UPLOAD_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../uploads")
)

# Establish isolated test engine and session factory
async_test_engine = create_async_engine(DATABASE_URL, echo=False)
async_test_session_factory = async_sessionmaker(
    bind=async_test_engine, class_=AsyncSession, expire_on_commit=False
)

# Single unified test application
test_app = FastAPI()
test_app.include_router(router)


@pytest_asyncio.fixture(autouse=True)
async def setup_test_db():
    """Ensure that the database schema is fully updated and clean before running tests.
    
    Using function scope prevents event loop mismatch issues with asyncpg connections.
    """
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    
    # Run Alembic migrations synchronously on the test database
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    
    yield
    
    # Downgrade on exit to keep test environment clean
    command.downgrade(config, "base")
    await async_test_engine.dispose()


@pytest_asyncio.fixture()
async def db_session():
    """Provides a transaction-isolated AsyncSession that automatically rolls back after each test."""
    async with async_test_engine.connect() as connection:
        transaction = await connection.begin()
        async_session = AsyncSession(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        try:
            yield async_session
        finally:
            await async_session.close()
            await transaction.rollback()


# ──────────────────────────────────────────────────────────────────────
# 1. UNIT VALIDATION TESTS (Mocked DB Session + Async HTTPX)
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture()
def mock_db_override():
    """Override database dependency with an isolated Mock session to prevent database hits."""
    async def _get_db_override():
        mock_db = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result
        yield mock_db

    test_app.dependency_overrides[get_db] = _get_db_override
    yield
    test_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_upload_rejections_file_size_exceeded(mock_db_override):
    """Assert that a file exceeding the maximum size limit is synchronously rejected with 413."""
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Prepend %PDF magic bytes so the MIME validation passes first
        large_content = b"%PDF-1.4\n" + b"a" * (2 * 1024 * 1024)  # 2MB
        
        # Patch local size limit helper directly to target 1MB limit
        with patch("app.documents.routes.get_max_pdf_size_mb", return_value=1):
            response = await client.post(
                "/api/v1/documents",
                files={"file": ("large_file.pdf", large_content, "application/pdf")},
            )
            assert response.status_code == 413
            assert "exceeds the maximum ceiling" in response.json()["detail"]


@pytest.mark.asyncio
async def test_upload_rejections_invalid_magic_bytes(mock_db_override):
    """Assert that a non-PDF file disguised with a .pdf extension is rejected with 415."""
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        fake_pdf_content = b"This is not a PDF file. This is plain text."
        response = await client.post(
            "/api/v1/documents",
            files={"file": ("fake_disguised_file.pdf", fake_pdf_content, "application/pdf")},
        )
        assert response.status_code == 415
        assert "Unsupported Media Type" in response.json()["detail"]


@pytest.mark.asyncio
async def test_upload_rejections_page_count_exceeded(mock_db_override):
    """Assert that a valid PDF exceeding the page count ceiling is rejected with 413."""
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        pdf_content = b"%PDF-1.4\n%mock_pdf_pages"
        
        mock_pdf = MagicMock()
        mock_pdf.__enter__.return_value = mock_pdf
        mock_pdf.__exit__.return_value = None
        mock_pdf.pages = [MagicMock() for _ in range(10)]  # Mock 10 pages
        
        # Patch local pages limit helper directly to target 5 pages limit
        with patch("app.documents.routes.get_max_pdf_pages", return_value=5):
            with patch("app.documents.routes.pdfplumber.open", return_value=mock_pdf):
                response = await client.post(
                    "/api/v1/documents",
                    files={"file": ("too_many_pages.pdf", pdf_content, "application/pdf")},
                )
                assert response.status_code == 413
                assert "exceeds maximum allowed boundary" in response.json()["detail"]


@pytest.mark.asyncio
async def test_upload_rejections_invalid_pdf_format(mock_db_override):
    """Assert that a corrupted PDF file triggers a 422 Unprocessable Entity error."""
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        pdf_content = b"%PDF-1.4\ncorrupted_data_here"
        
        with patch("app.documents.routes.pdfplumber.open", side_effect=Exception("Corrupted PDF structure")):
            response = await client.post(
                "/api/v1/documents",
                files={"file": ("corrupted.pdf", pdf_content, "application/pdf")},
            )
            assert response.status_code == 422
            assert "Unable to parse or read PDF pages" in response.json()["detail"]


# ──────────────────────────────────────────────────────────────────────
# 2. DATABASE INTEGRATION TESTS (Rollback-Isolated DB Session + Async HTTPX)
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture()
def real_db_override(db_session):
    """Override database dependency with the live rollback-isolated session."""
    async def _get_db_override():
        yield db_session

    test_app.dependency_overrides[get_db] = _get_db_override
    yield
    test_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_upload_flow_success_and_cascade_delete(db_session, real_db_override):
    """Test the complete upload lifecycle: upload -> poll -> list -> delete."""
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        pdf_content = b"%PDF-1.4\n%mock_pdf_pages_ok"
        
        mock_pdf = MagicMock()
        mock_pdf.__enter__.return_value = mock_pdf
        mock_pdf.__exit__.return_value = None
        mock_pdf.pages = [MagicMock() for _ in range(3)]  # 3 pages
        
        # 1. POST /api/v1/documents - Valid Upload
        with patch("app.documents.routes.pdfplumber.open", return_value=mock_pdf):
            response = await client.post(
                "/api/v1/documents",
                files={"file": ("sample_test_doc.pdf", pdf_content, "application/pdf")},
            )
            assert response.status_code == 202
            data = response.json()
            doc_id = data["id"]
            assert data["status"] == "processing"
            assert data["filename"] == "sample_test_doc.pdf"
            assert data["page_count"] == 3
            assert data["deduplicated"] is False

        # 2. GET /api/v1/documents/{id} - Poll Status
        poll_response = await client.get(f"/api/v1/documents/{doc_id}")
        assert poll_response.status_code == 200
        poll_data = poll_response.json()
        assert poll_data["id"] == doc_id
        assert poll_data["status"] == "processing"
        assert poll_data["page_count"] == 3

        # 3. GET /api/v1/documents - List Documents
        list_response = await client.get("/api/v1/documents")
        assert list_response.status_code == 200
        list_data = list_response.json()
        # Check that our newly uploaded document is in the list
        matching_docs = [d for d in list_data if d["id"] == doc_id]
        assert len(matching_docs) == 1
        assert matching_docs[0]["filename"] == "sample_test_doc.pdf"

        # Verify physical file exists on local storage
        # Extract hash to verify path
        stmt = select(Document).where(Document.id == UUID(doc_id))
        db_doc = (await db_session.execute(stmt)).scalar_one()
        file_path = os.path.join(UPLOAD_DIR, f"{db_doc.content_hash}.pdf")
        assert os.path.exists(file_path)

        # 4. DELETE /api/v1/documents/{id} - Delete and clean up
        delete_response = await client.delete(f"/api/v1/documents/{doc_id}")
        assert delete_response.status_code == 200
        delete_data = delete_response.json()
        assert delete_data["id"] == doc_id
        assert delete_data["deleted"] is True

        # Verify physical file is removed from disk
        assert not os.path.exists(file_path)

        # Verify document row is deleted from DB
        deleted_check = (await db_session.execute(stmt)).scalar_one_or_none()
        assert deleted_check is None


@pytest.mark.asyncio
async def test_upload_flow_deduplication(db_session, real_db_override):
    """Test idempotent short-circuiting when re-uploading an identical indexed document."""
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        pdf_content = b"%PDF-1.4\n%mock_pdf_pages_dedup"
        
        mock_pdf = MagicMock()
        mock_pdf.__enter__.return_value = mock_pdf
        mock_pdf.__exit__.return_value = None
        mock_pdf.pages = [MagicMock() for _ in range(5)]
        
        with patch("app.documents.routes.pdfplumber.open", return_value=mock_pdf):
            # First Upload -> processing
            response1 = await client.post(
                "/api/v1/documents",
                files={"file": ("unique_doc.pdf", pdf_content, "application/pdf")},
            )
            doc_id = response1.json()["id"]

            # Simulate background worker completion by marking the document as 'indexed'
            stmt = select(Document).where(Document.id == UUID(doc_id))
            doc = (await db_session.execute(stmt)).scalar_one()
            doc.status = "indexed"
            await db_session.commit()

            # Second Upload of identical content -> Short circuits with 'indexed'
            response2 = await client.post(
                "/api/v1/documents",
                files={"file": ("duplicate_doc.pdf", pdf_content, "application/pdf")},
            )
            assert response2.status_code == 202
            data2 = response2.json()
            assert data2["id"] == doc_id
            assert data2["status"] == "indexed"
            assert data2["deduplicated"] is True
