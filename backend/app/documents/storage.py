"""Document and page-image storage helpers."""

from __future__ import annotations

import os
from pathlib import Path

from app.settings import settings


def put_document_bytes(content_hash: str, filename: str, data: bytes, local_dir: Path) -> str:
    """Store an uploaded PDF and return its storage reference."""
    backend = settings.upload_storage_backend
    if backend == "local":
        local_dir.mkdir(parents=True, exist_ok=True)
        local_path = local_dir / f"{content_hash}.pdf"
        local_path.write_bytes(data)
        return str(local_path)
    if backend == "s3":
        bucket = settings.s3_document_bucket or settings.s3_bucket_name
        if not bucket:
            raise RuntimeError("S3_BUCKET_NAME or S3_DOCUMENT_BUCKET is required for S3 document storage")
        key = f"documents/{content_hash}/{_safe_name(filename)}"
        _s3_client().put_object(Bucket=bucket, Key=key, Body=data, ContentType="application/pdf")
        return f"s3://{bucket}/{key}"
    raise RuntimeError(f"Unsupported upload storage backend: {backend}")


def put_page_image_bytes(document_id: str, page_number: int, data: bytes, local_path: Path) -> str:
    """Store a rasterized page image and return its storage reference."""
    backend = settings.page_image_storage_backend
    if backend == "local":
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(data)
        return str(local_path)
    if backend == "s3":
        bucket = settings.s3_page_image_bucket or settings.s3_bucket_name
        if not bucket:
            raise RuntimeError("S3_BUCKET_NAME or S3_PAGE_IMAGE_BUCKET is required for S3 page-image storage")
        key = f"page_images/{document_id}/{page_number:04d}.png"
        _s3_client().put_object(Bucket=bucket, Key=key, Body=data, ContentType="image/png")
        return f"s3://{bucket}/{key}"
    raise RuntimeError(f"Unsupported page image storage backend: {backend}")


def delete_document_ref(storage_ref: str | None, content_hash: str, local_dir: Path) -> None:
    """Best-effort physical document cleanup."""
    if settings.upload_storage_backend == "local":
        path = Path(storage_ref) if storage_ref else local_dir / f"{content_hash}.pdf"
        if path.exists():
            path.unlink()
        return
    if settings.upload_storage_backend == "s3" and storage_ref:
        bucket, key = _parse_s3_ref(storage_ref)
        _s3_client().delete_object(Bucket=bucket, Key=key)


def _s3_client():  # type: ignore[no-untyped-def]
    try:
        import boto3  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("boto3 is required when an S3 storage backend is configured") from exc
    kwargs = {"region_name": settings.aws_region} if settings.aws_region else {}
    return boto3.client("s3", **kwargs)


def _parse_s3_ref(storage_ref: str) -> tuple[str, str]:
    if not storage_ref.startswith("s3://"):
        raise RuntimeError(f"Expected s3:// storage ref, got {storage_ref}")
    bucket_and_key = storage_ref.removeprefix("s3://")
    bucket, key = bucket_and_key.split("/", 1)
    return bucket, key


def _safe_name(filename: str) -> str:
    basename = os.path.basename(filename or "uploaded_document.pdf")
    return basename or "uploaded_document.pdf"
