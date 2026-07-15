from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import DATABASE_URL
from app.models import Document, PageImage
from app.worker import UPLOAD_DIR, process_document

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class FakeEmbeddingClient:
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[0.01] * 1536 for _ in texts]


class FakeImage:
    def save(self, path: str | Path, image_format: str) -> None:
        if hasattr(path, "write"):
            path.write(b"fake-png")
            return
        Path(path).write_bytes(b"fake-png")


class FakeTable:
    bbox = (10, 10, 100, 100)


class FakePage:
    width = 100
    height = 100
    images: list[object] = []
    objects: dict[str, list[object]] = {}

    def extract_text(self) -> str:
        return "MALARIA PROTOCOL\nGive artemisinin combination therapy with food"

    def find_tables(self) -> list[FakeTable]:
        return [FakeTable()]

    def extract_tables(self) -> list[list[list[str]]]:
        return [[["Drug", "Dose"], ["ACT", "one tablet"]]]


class FakePdf:
    pages = [FakePage()]

    def __enter__(self) -> "FakePdf":
        return self

    def __exit__(self, *args: object) -> None:
        return None


@pytest_asyncio.fixture(autouse=True)
async def setup_test_db():
    """Rebuild the schema for an isolated rasterization worker test."""
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))

    command.downgrade(config, "base")
    command.upgrade(config, "head")

    yield

    command.downgrade(config, "base")


@pytest.mark.asyncio
async def test_rasterization_and_struct_detection(monkeypatch: pytest.MonkeyPatch):
    """The worker rasterizes structured pages, persists chunks, and marks the document indexed."""
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_test_session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    short_hash = "test_hash_123"
    pdf_path = Path(UPLOAD_DIR) / f"{short_hash}.pdf"

    monkeypatch.setattr("app.documents.processing.pdfplumber.open", lambda *_args, **_kwargs: FakePdf())
    monkeypatch.setattr("app.documents.chunking.pdfplumber.open", lambda *_args, **_kwargs: FakePdf())
    monkeypatch.setattr("app.documents.processing.convert_from_path", lambda *_args, **_kwargs: [FakeImage()])
    # This is a hermetic test of the worker's deterministic rasterization path. Force the
    # deterministic planner so it never reaches for a real provider key that happens to be
    # present in the container environment.
    monkeypatch.setattr("app.agents.ingestion_agent.default_ingestion_client", lambda: None)

    async with async_test_session_factory() as db:
        doc = Document(
            filename="test_pdf.pdf",
            content_hash=short_hash,
            status="processing",
            page_count=1,
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)
        doc_id = doc.id

    try:
        Path(UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(b"%PDF-1.4\n")

        await process_document(doc_id, embedding_client=FakeEmbeddingClient())

        async with async_test_session_factory() as db:
            result = await db.execute(select(Document).where(Document.id == doc_id))
            updated_doc = result.scalar_one()
            assert updated_doc.status == "indexed"
            assert updated_doc.metadata_["structure_detection_status"] == "completed"
            assert updated_doc.metadata_["chunking_status"] == "completed"

            result_imgs = await db.execute(select(PageImage).where(PageImage.document_id == doc_id))
            images = result_imgs.scalars().all()
            assert len(images) == 1
            assert images[0].page_number == 1
            assert images[0].has_table is True
            assert Path(images[0].storage_ref).exists()
    finally:
        if pdf_path.exists():
            pdf_path.unlink()
        await engine.dispose()
