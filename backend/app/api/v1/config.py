"""Public read-only configuration endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.settings import settings

router = APIRouter(prefix="/api/v1/config", tags=["config"])


@router.get("/upload-limits")
async def upload_limits() -> dict[str, object]:
    return {
        "max_size_mb": settings.max_pdf_size_mb,
        "max_pages": settings.max_pdf_pages,
        "allowed_mime_types": settings.allowed_mime_type_list,
    }
