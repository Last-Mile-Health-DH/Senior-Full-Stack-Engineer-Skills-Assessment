import hashlib
import io
import logging
from pathlib import Path
from uuid import UUID
import pdfplumber

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile, HTTPException, status
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Document
from app.documents.storage import delete_document_ref, put_document_bytes
from app.settings import settings
from app.worker import process_document

# Router setup
router = APIRouter(prefix="/api/v1/documents", tags=["documents"])
logger = logging.getLogger(__name__)


def get_max_pdf_size_mb() -> int:
    """Read the maximum allowed PDF size (in MB) from settings."""
    return settings.max_pdf_size_mb


def get_max_pdf_pages() -> int:
    """Read the maximum allowed PDF pages from settings."""
    return settings.max_pdf_pages


def get_upload_storage_backend() -> str:
    """Read the configured storage engine."""
    return settings.upload_storage_backend


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Enforce size/MIME/page limit checks, deduplicate content, and enqueue ingestion."""
    # Retrieve limits dynamically using getter helpers for perfect test mock surface
    max_pdf_size_mb = get_max_pdf_size_mb()
    max_pdf_pages = get_max_pdf_pages()
    upload_storage_backend = get_upload_storage_backend()

    # Resolve upload storage path relative to the app/ directory
    upload_dir = Path(__file__).resolve().parents[1] / "uploads"

    # 1. Read file bytes and reset pointer immediately
    await file.seek(0)
    file_bytes = await file.read()
    await file.seek(0)  # Keep pointer clean

    # 2. Validate File Size synchronously at the edge
    size_bytes = len(file_bytes)
    size_mb = size_bytes / (1024 * 1024)
    if size_mb > max_pdf_size_mb:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Request Entity Too Large: File size {size_mb:.2f}MB exceeds the maximum ceiling of {max_pdf_size_mb}MB."
        )

    # 3. Validate MIME Type by inspecting real file header bytes, not name extensions
    magic_bytes = file_bytes[:4]
    if magic_bytes != b"%PDF":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported Media Type: File must be a valid PDF with correct magic headers (%PDF)."
        )

    # 4. Validate Page Count via pdfplumber cheaply before persisting/indexing
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            page_count = len(pdf.pages)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unprocessable Entity: Unable to parse or read PDF pages. Details: {str(e)}"
        )

    if page_count > max_pdf_pages:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Request Entity Too Large: Page count {page_count} exceeds maximum allowed boundary of {max_pdf_pages} pages."
        )

    # 5. Compute SHA-256 Content Hash for deduplication
    content_hash = hashlib.sha256(file_bytes).hexdigest()

    # 6. Idempotent Deduplication Check
    stmt = select(Document).where(Document.content_hash == content_hash)
    result = await db.execute(stmt)
    existing_document = result.scalar_one_or_none()

    if existing_document:
        # If the file already exists and is in a working state, return it immediately
        if existing_document.status in ("indexed", "processing"):
            return {
                "id": str(existing_document.id),
                "status": existing_document.status,
                "filename": existing_document.filename,
                "page_count": existing_document.page_count,
                "deduplicated": True,
            }
        else:
            # If a prior ingestion failed, clean it up and allow a fresh upload
            await db.delete(existing_document)
            await db.commit()

    # 7. Store file in the configured backend.
    storage_ref = put_document_bytes(
        content_hash=content_hash,
        filename=file.filename or "uploaded_document.pdf",
        data=file_bytes,
        local_dir=upload_dir,
    )

    # 8. Persist Document metadata in the PostgreSQL relational DB
    new_doc = Document(
        filename=file.filename or "uploaded_document.pdf",
        content_hash=content_hash,
        status="processing",
        page_count=page_count,
        metadata_={"storage_backend": upload_storage_backend, "storage_ref": storage_ref}
    )
    db.add(new_doc)
    await db.commit()
    await db.refresh(new_doc)
    background_tasks.add_task(_process_document_background, new_doc.id)

    return {
        "id": str(new_doc.id),
        "status": new_doc.status,
        "filename": new_doc.filename,
        "page_count": new_doc.page_count,
        "deduplicated": False,
    }


async def _process_document_background(document_id: UUID) -> None:
    """Run ingestion after the upload response without surfacing worker failures to the client."""
    try:
        await process_document(document_id)
    except Exception:
        logger.exception("document_ingestion.background_failed document_id=%s", document_id)


@router.get("/{document_id}")
async def get_document_status(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve document record for processing status polling."""
    stmt = select(Document).where(Document.id == document_id)
    result = await db.execute(stmt)
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail=f"Document with ID {document_id} was not found."
        )

    return {
        "id": str(document.id),
        "filename": document.filename,
        "status": document.status,
        "page_count": document.page_count,
        "uploaded_at": document.uploaded_at.isoformat() if document.uploaded_at else None,
        "metadata": document.metadata_
    }


@router.get("")
async def list_documents(
    db: AsyncSession = Depends(get_db),
):
    """List all documents to populate frontend management table."""
    stmt = select(Document).order_by(desc(Document.uploaded_at))
    result = await db.execute(stmt)
    documents = result.scalars().all()

    return [
        {
            "id": str(doc.id),
            "filename": doc.filename,
            "status": doc.status,
            "page_count": doc.page_count,
            "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
            "metadata": doc.metadata_
        }
        for doc in documents
    ]


@router.delete("/{document_id}")
async def delete_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete document from relational DB and clean up its physical file on disk."""
    stmt = select(Document).where(Document.id == document_id)
    result = await db.execute(stmt)
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail=f"Document with ID {document_id} was not found."
        )

    # 1. Clean up physical file on disk
    upload_storage_backend = get_upload_storage_backend()
    upload_dir = Path(__file__).resolve().parents[1] / "uploads"
    try:
        delete_document_ref(
            storage_ref=(document.metadata_ or {}).get("storage_ref"),
            content_hash=str(document.content_hash).strip(),
            local_dir=upload_dir,
        )
    except OSError:
        pass

    # 2. Clean up Postgres database row (ON DELETE CASCADE cleans up chunks/page_images)
    await db.delete(document)
    await db.commit()

    return {
        "id": str(document_id),
        "deleted": True,
        "detail": f"Document {document_id} and all associated chunks/images deleted successfully."
    }
