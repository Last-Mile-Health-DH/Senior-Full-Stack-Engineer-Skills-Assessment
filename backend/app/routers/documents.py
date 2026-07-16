from fastapi import APIRouter, Depends, UploadFile
from langchain_openai.embeddings import OpenAIEmbeddings
from psycopg_pool import ConnectionPool
from sentence_transformers import SentenceTransformer

from app.core.config import Settings
from app.deps import get_db_pool, get_embedder, get_openai_embeddings, get_settings
from app.schemas import DocumentFile, DocumentListResponse, UploadResponse
from app.services.ingestion import fetch_document_files, ingest_document, validate_pdf_upload

router = APIRouter()


@router.get("/documents", response_model=DocumentListResponse)
def list_documents(pool: ConnectionPool = Depends(get_db_pool)) -> DocumentListResponse:
    rows = fetch_document_files(pool)
    return DocumentListResponse(
        documents=[
            DocumentFile(id=r[0], doc_name=r[1], file_size=r[2], page_count=r[3], file_type=r[4], created_at=r[5])
            for r in rows
        ]
    )


@router.post("/documents", response_model=UploadResponse)
def upload_document(
    file: UploadFile,
    pool: ConnectionPool = Depends(get_db_pool),
    embedder: SentenceTransformer = Depends(get_embedder),
    openai_embeddings: OpenAIEmbeddings = Depends(get_openai_embeddings),
    settings: Settings = Depends(get_settings),
) -> UploadResponse:
    file_bytes = file.file.read()
    validate_pdf_upload(file_bytes, file.filename, file.content_type, settings.max_upload_mb)

    chunks_ingested = ingest_document(
        file_bytes,
        file.filename or "uploaded.pdf",
        embedder=embedder,
        openai_embeddings=openai_embeddings,
        pool=pool,
        settings=settings,
    )

    return UploadResponse(doc_name=file.filename or "uploaded.pdf", chunks_ingested=chunks_ingested)
