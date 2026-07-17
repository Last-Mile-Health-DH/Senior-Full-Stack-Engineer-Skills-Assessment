"""BC4 PDF structure detection and page rasterization worker."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

import pdfplumber
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, PageImage

try:  # pragma: no cover - exercised through patched call sites in unit tests.
    from pdf2image import convert_from_path
except ImportError:  # pragma: no cover
    convert_from_path = None  # type: ignore[assignment]

try:  # pragma: no cover - exercised through patched call sites in unit tests.
    import pytesseract
except ImportError:  # pragma: no cover
    pytesseract = None  # type: ignore[assignment]


JSONValue = dict[str, Any]


@dataclass(slots=True)
class PageStructureResult:
    """Structure signals produced for one PDF page."""

    page_number: int
    has_table: bool
    has_figure: bool
    table_bboxes: list[tuple[float, float, float, float]]
    text_char_count: int
    text_yield_ratio: float
    heading_candidates: list[str]
    extraction_confidence: str
    ocr_text: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ProcessingSummary:
    """Worker output used by tests and later orchestration cycles."""

    document_id: UUID
    processed_pages: int
    rasterized_pages: int
    table_pages: list[int]
    figure_pages: list[int]
    low_yield_pages: list[int]
    status: str
    errors: list[str]


def get_upload_dir() -> Path:
    """Return the local PDF upload directory used by BC3."""
    return Path(__file__).resolve().parents[2] / "uploads"


def get_page_image_dir() -> Path:
    """Return the local page-image storage directory."""
    return Path(__file__).resolve().parents[2] / "page_images"


def get_page_image_dpi() -> int:
    """Read the configured rasterization DPI."""
    return int(os.getenv("PAGE_IMAGE_DPI", "200"))


def get_ocr_text_yield_threshold() -> float:
    """Read the low-text-yield OCR threshold."""
    return float(os.getenv("OCR_TEXT_YIELD_THRESHOLD", "0.15"))


def get_page_image_storage_backend() -> str:
    """Read the configured page-image storage backend."""
    return os.getenv("PAGE_IMAGE_STORAGE_BACKEND", "local")


def resolve_document_pdf_path(document: Document) -> Path:
    """Resolve the local uploaded PDF path for a document row."""
    metadata = document.metadata_ or {}
    storage_ref = metadata.get("storage_ref")
    if isinstance(storage_ref, str) and storage_ref:
        path = Path(storage_ref)
        if path.is_absolute():
            return path
        return get_upload_dir().parent / path

    return get_upload_dir() / f"{str(document.content_hash).strip()}.pdf"


def detect_page_structure(
    page: Any,
    page_number: int,
    ocr_text_yield_threshold: float | None = None,
) -> PageStructureResult:
    """Detect tables, figure-like objects, low text yield, and heading candidates."""
    threshold = (
        get_ocr_text_yield_threshold()
        if ocr_text_yield_threshold is None
        else ocr_text_yield_threshold
    )

    text = _extract_text(page)
    text_char_count = len(text)
    text_yield_ratio = _calculate_text_yield_ratio(page, text_char_count)

    table_bboxes = _find_table_bboxes(page)
    has_figure = _detect_figure_like_content(page)
    extraction_confidence = (
        "low_yield_needs_ocr"
        if text_yield_ratio < threshold
        else "native_text"
    )

    return PageStructureResult(
        page_number=page_number,
        has_table=len(table_bboxes) > 0,
        has_figure=has_figure,
        table_bboxes=table_bboxes,
        text_char_count=text_char_count,
        text_yield_ratio=text_yield_ratio,
        heading_candidates=_extract_heading_candidates(text),
        extraction_confidence=extraction_confidence,
    )


def extract_text_ocr_fallback(
    pdf_path: Path,
    page_number: int,
    dpi: int | None = None,
) -> str:
    """Rasterize one page and run Tesseract OCR over it."""
    if convert_from_path is None:
        raise RuntimeError("pdf2image is not installed")
    if pytesseract is None:
        raise RuntimeError("pytesseract is not installed")

    images = convert_from_path(
        str(pdf_path),
        dpi=dpi or get_page_image_dpi(),
        first_page=page_number,
        last_page=page_number,
        fmt="png",
    )
    if not images:
        return ""
    return str(pytesseract.image_to_string(images[0]) or "").strip()


def rasterize_page_to_local_storage(
    pdf_path: Path,
    document: Document,
    page_number: int,
    dpi: int | None = None,
) -> str:
    """Rasterize one PDF page to a local PNG and return its storage reference."""
    if get_page_image_storage_backend() != "local":
        raise RuntimeError("Only local page-image storage is supported before BC18")
    if convert_from_path is None:
        raise RuntimeError("pdf2image is not installed")

    output_dir = get_page_image_dir() / str(document.content_hash).strip()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"page_{page_number:04d}.png"

    images = convert_from_path(
        str(pdf_path),
        dpi=dpi or get_page_image_dpi(),
        first_page=page_number,
        last_page=page_number,
        fmt="png",
    )
    if not images:
        raise RuntimeError(f"Unable to rasterize page {page_number}")

    images[0].save(output_path, "PNG")
    return str(output_path)


async def process_document_structure(
    db: AsyncSession,
    document: Document,
) -> ProcessingSummary:
    """Run BC4 structure detection and page-image persistence for one document."""
    pdf_path = resolve_document_pdf_path(document)
    errors: list[str] = []
    if not pdf_path.exists():
        document.status = "failed"
        document.metadata_ = _merged_metadata(
            document,
            {
                "structure_detection_status": "failed",
                "structure_detection_error": f"Uploaded PDF not found at {pdf_path}",
            },
        )
        await db.commit()
        return ProcessingSummary(
            document_id=document.id,
            processed_pages=0,
            rasterized_pages=0,
            table_pages=[],
            figure_pages=[],
            low_yield_pages=[],
            status="failed",
            errors=[f"Uploaded PDF not found at {pdf_path}"],
        )

    page_results: list[PageStructureResult] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for index, page in enumerate(pdf.pages, start=1):
                result = detect_page_structure(page, index)
                if result.extraction_confidence == "low_yield_needs_ocr":
                    try:
                        result.ocr_text = extract_text_ocr_fallback(pdf_path, index)
                    except Exception as exc:  # deterministic fallback: continue without OCR text.
                        message = f"OCR fallback failed on page {index}: {exc}"
                        result.warnings.append(message)
                        errors.append(message)
                page_results.append(result)
    except Exception as exc:
        document.status = "failed"
        document.metadata_ = _merged_metadata(
            document,
            {
                "structure_detection_status": "failed",
                "structure_detection_error": str(exc),
            },
        )
        await db.commit()
        return ProcessingSummary(
            document_id=document.id,
            processed_pages=0,
            rasterized_pages=0,
            table_pages=[],
            figure_pages=[],
            low_yield_pages=[],
            status="failed",
            errors=[str(exc)],
        )

    await db.execute(delete(PageImage).where(PageImage.document_id == document.id))

    rasterized_pages = 0
    for result in page_results:
        if not result.has_table and not result.has_figure:
            continue

        try:
            storage_ref = rasterize_page_to_local_storage(pdf_path, document, result.page_number)
        except Exception as exc:
            errors.append(f"Rasterization failed on page {result.page_number}: {exc}")
            continue

        db.add(
            PageImage(
                document_id=document.id,
                page_number=result.page_number,
                storage_ref=storage_ref,
                has_table=result.has_table,
                has_figure=result.has_figure,
            )
        )
        rasterized_pages += 1

    table_pages = [result.page_number for result in page_results if result.has_table]
    figure_pages = [result.page_number for result in page_results if result.has_figure]
    low_yield_pages = [
        result.page_number
        for result in page_results
        if result.extraction_confidence == "low_yield_needs_ocr"
    ]

    document.metadata_ = _merged_metadata(
        document,
        {
            "structure_detection_status": "completed",
            "structure_detection_version": _structure_detection_version(),
            "structure_detection": {
                "processed_pages": len(page_results),
                "rasterized_pages": rasterized_pages,
                "table_pages": table_pages,
                "figure_pages": figure_pages,
                "low_yield_pages": low_yield_pages,
                "errors": errors,
            },
        },
    )
    await db.commit()

    return ProcessingSummary(
        document_id=document.id,
        processed_pages=len(page_results),
        rasterized_pages=rasterized_pages,
        table_pages=table_pages,
        figure_pages=figure_pages,
        low_yield_pages=low_yield_pages,
        status="processing",
        errors=errors,
    )


async def process_next_processing_document(db: AsyncSession) -> ProcessingSummary | None:
    """Pick up the oldest unprocessed document with status=processing."""
    result = await db.execute(select(Document).where(Document.status == "processing").order_by(Document.uploaded_at))
    documents = result.scalars().all()
    for document in documents:
        if (document.metadata_ or {}).get("structure_detection_status") == "completed":
            continue
        return await process_document_structure(db, document)
    return None


async def process_processing_documents(
    db: AsyncSession,
    limit: int = 10,
) -> list[ProcessingSummary]:
    """Process pending documents up to the provided limit."""
    summaries: list[ProcessingSummary] = []
    while len(summaries) < limit:
        summary = await process_next_processing_document(db)
        if summary is None:
            break
        summaries.append(summary)
    return summaries


def _extract_text(page: Any) -> str:
    try:
        return str(page.extract_text() or "")
    except Exception:
        return ""


def _find_table_bboxes(page: Any) -> list[tuple[float, float, float, float]]:
    try:
        tables = page.find_tables() or []
    except Exception:
        tables = []

    bboxes: list[tuple[float, float, float, float]] = []
    for table in tables:
        bbox = getattr(table, "bbox", None)
        if _is_bbox(bbox):
            bboxes.append((float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])))
    return bboxes


def _detect_figure_like_content(page: Any) -> bool:
    images = getattr(page, "images", None)
    if images:
        return True

    objects = getattr(page, "objects", {}) or {}
    for object_type in ("rect", "curve", "line"):
        if len(objects.get(object_type, []) or []) >= 8:
            return True
    return False


def _calculate_text_yield_ratio(page: Any, text_char_count: int) -> float:
    width = float(getattr(page, "width", 0) or 0)
    height = float(getattr(page, "height", 0) or 0)
    if width <= 0 or height <= 0:
        bbox = getattr(page, "bbox", None)
        if _is_bbox(bbox):
            width = float(bbox[2]) - float(bbox[0])
            height = float(bbox[3]) - float(bbox[1])

    area = max(width * height, 1.0)
    return text_char_count / (area / 1000.0)


def _extract_heading_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    for raw_line in text.splitlines():
        line = " ".join(raw_line.strip().split())
        if not line or len(line) > 120:
            continue

        letters = [character for character in line if character.isalpha()]
        uppercase_ratio = (
            sum(1 for character in letters if character.isupper()) / len(letters)
            if letters
            else 0.0
        )
        starts_like_section = bool(line[:1].isdigit()) or line.lower().startswith(
            ("chapter ", "section ", "appendix ")
        )
        if uppercase_ratio >= 0.65 or starts_like_section:
            candidates.append(line)

    return candidates[:10]


def _is_bbox(value: object) -> bool:
    return isinstance(value, (tuple, list)) and len(value) == 4


def _structure_detection_version() -> JSONValue:
    return {
        "table_detection_method": os.getenv("TABLE_DETECTION_METHOD", "pdfplumber"),
        "page_image_dpi": get_page_image_dpi(),
        "ocr_engine": os.getenv("OCR_ENGINE", "tesseract"),
        "ocr_text_yield_threshold": get_ocr_text_yield_threshold(),
    }


def _merged_metadata(document: Document, values: JSONValue) -> JSONValue:
    metadata = dict(document.metadata_ or {})
    metadata.update(values)
    return metadata
