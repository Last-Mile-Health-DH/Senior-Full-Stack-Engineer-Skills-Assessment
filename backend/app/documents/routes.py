import os
import hashlib
import io
from typing import Any
from uuid import UUID
import pdfplumber
from dotenv import load_dotenv

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, Header, status
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Document

# Load environment variables
load_dotenv()

# Router setup
router = APIRouter(prefix="/api/v1/documents", tags=["documents"])


def get_max_pdf_size_mb() -> int:
    """Read the maximum allowed PDF size (in MB) from environment."""
    return int(os.getenv("MAX_PDF_SIZE_MB", "20"))


def get_max_pdf_pages() -> int:
    """Read the maximum allowed PDF pages from environment."""
    return int(os.getenv("MAX_PDF_PAGES", "300"))


def get_upload_storage_backend() -> str:
    """Read the configured storage engine."""
    return os.getenv("UPLOAD_STORAGE_BACKEND", "local")


async def get_current_user_stub(authorization: str | None = Header(None)) -> dict[str, Any]:
    """Stub dependency for authentication, pending robust JWT implementation in BC15."""
    # This is a pass-through dependency to satisfy the API contract.
    # In BC15, this will extract, verify, and parse the signed JWT from the Header.
    return {
        "user_id": "placeholder_session_user", 
        "role": "authenticated_user", 
        "stubbed": True
    }


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict[str, Any] = Depends(get_current_user_stub),
):
    """Enforce size/MIME/page limit checks, handle content-hash dedup, and accept PDF for ingestion."""
    # Retrieve limits dynamically using getter helpers for perfect test mock surface
    max_pdf_size_mb = get_max_pdf_size_mb()
    max_pdf_pages = get_max_pdf_pages()
    upload_storage_backend = get_upload_storage_backend()

    # Resolve upload storage path relative to the app/ directory
    upload_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../uploads")
    )
    os.makedirs(upload_dir, exist_ok=True)

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

    # 7. Store file locally
    if upload_storage_backend == "local":
        local_path = os.path.join(upload_dir, f"{content_hash}.pdf")
        with open(local_path, "wb") as f:
            f.write(file_bytes)
    else:
        # Placeholder for other storage engines (e.g. S3 at BC18)
        pass

    # 8. Persist Document metadata in the PostgreSQL relational DB
    new_doc = Document(
        filename=file.filename or "uploaded_document.pdf",
        content_hash=content_hash,
        status="processing",
        page_count=page_count,
        metadata_={"storage_backend": upload_storage_backend}
    )
    db.add(new_doc)
    await db.commit()
    await db.refresh(new_doc)

    return {
        "id": str(new_doc.id),
        "status": new_doc.status,
        "filename": new_doc.filename,
        "page_count": new_doc.page_count,
        "deduplicated": False,
    }


@router.get("/{document_id}")
async def get_document_status(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict[str, Any] = Depends(get_current_user_stub),
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
    current_user: dict[str, Any] = Depends(get_current_user_stub),
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
    current_user: dict[str, Any] = Depends(get_current_user_stub),
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
    upload_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../uploads")
    )
    if upload_storage_backend == "local":
        local_path = os.path.join(upload_dir, f"{document.content_hash}.pdf")
        if os.path.exists(local_path):
            try:
                os.remove(local_path)
            except OSError:
                # Log but proceed with DB delete to prevent data mismatches
                pass

    # 2. Clean up Postgres database row (ON DELETE CASCADE cleans up chunks/page_images)
    await db.delete(document)
    await db.commit()

    return {
        "id": str(document_id),
        "deleted": True,
        "detail": f"Document {document_id} and all associated chunks/images deleted successfully."
    }
