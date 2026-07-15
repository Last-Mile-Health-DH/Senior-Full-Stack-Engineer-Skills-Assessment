from __future__ import annotations

from app.settings import settings as _settings


def test_request_body_limit_admits_a_maximum_size_upload() -> None:
    """A legal upload must not be killed by the body guard before it is even validated.

    If REQUEST_BODY_SIZE_LIMIT_BYTES sits below MAX_PDF_SIZE_MB, the middleware returns a
    generic "body too large" for a file the upload policy explicitly allows, and the user
    is told nothing useful.
    """
    max_upload_bytes = _settings.max_pdf_size_mb * 1024 * 1024
    assert _settings.request_body_size_limit_bytes > max_upload_bytes, (
        "request_body_size_limit_bytes must exceed max_pdf_size_mb plus multipart overhead"
    )

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.config import router
from app.settings import settings


@pytest.mark.asyncio
async def test_upload_limits_endpoint_returns_settings_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "max_pdf_size_mb", 11)
    monkeypatch.setattr(settings, "max_pdf_pages", 22)
    monkeypatch.setattr(settings, "allowed_mime_types", "application/pdf")
    app = FastAPI()
    app.include_router(router)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/config/upload-limits")

    assert response.status_code == 200
    assert response.json() == {
        "max_size_mb": 11,
        "max_pages": 22,
        "allowed_mime_types": ["application/pdf"],
    }
