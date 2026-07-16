from io import BytesIO

import pdfplumber
from langchain_experimental.text_splitter import SemanticChunker
from langchain_openai.embeddings import OpenAIEmbeddings
from psycopg_pool import ConnectionPool
from sentence_transformers import SentenceTransformer

from app.core.config import Settings
from app.errors import IngestionError

PDF_MAGIC_BYTES = b"%PDF-"


def validate_pdf_upload(file_bytes: bytes, filename: str | None, content_type: str | None, max_upload_mb: int) -> None:
    if len(file_bytes) > max_upload_mb * 1024 * 1024:
        raise IngestionError(f"File exceeds the {max_upload_mb}MB upload limit.", status_code=413)

    looks_like_pdf = (content_type == "application/pdf") or bool(filename and filename.lower().endswith(".pdf"))
    if not looks_like_pdf or not file_bytes.startswith(PDF_MAGIC_BYTES):
        raise IngestionError("Uploaded file is not a valid PDF.", status_code=422)


def extract_text(file_bytes: bytes) -> str:
    text_content = ""
    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_content += page_text + "\n"

    if not text_content.strip():
        raise IngestionError(
            "No extractable text found in this PDF (it may be a scanned image without OCR).",
            status_code=422,
        )

    return text_content


def chunk_text(text: str, openai_embeddings: OpenAIEmbeddings, settings: Settings) -> list[str]:
    try:
        splitter = SemanticChunker(
            embeddings=openai_embeddings,
            breakpoint_threshold_type=settings.chunk_breakpoint_threshold_type,
            breakpoint_threshold_amount=settings.chunk_breakpoint_threshold_amount,
        )
        chunks = splitter.create_documents([text])
    except Exception as exc:
        raise IngestionError(f"Failed to chunk document: {exc}", status_code=502) from exc

    return [chunk.page_content for chunk in chunks if chunk.page_content.strip()]


def _vec_to_str(vector) -> str:
    return "[" + ",".join(str(x) for x in vector) + "]"


def store_chunks(doc_name: str, chunks: list[str], embedder: SentenceTransformer, pool: ConnectionPool) -> int:
    vectors = embedder.encode(chunks)

    with pool.connection() as conn:
        with conn.transaction():
            for chunk_text_value, vector in zip(chunks, vectors):
                conn.execute(
                    """
                    INSERT INTO documents (doc_name, chunk_text, embedding)
                    VALUES (%s, %s, %s::vector)
                    """,
                    (doc_name, chunk_text_value, _vec_to_str(vector)),
                )

    return len(chunks)


def ingest_document(
    file_bytes: bytes,
    doc_name: str,
    *,
    embedder: SentenceTransformer,
    openai_embeddings: OpenAIEmbeddings,
    pool: ConnectionPool,
    settings: Settings,
) -> int:
    text = extract_text(file_bytes)
    chunks = chunk_text(text, openai_embeddings, settings)

    if not chunks:
        raise IngestionError("Document produced no usable chunks after splitting.", status_code=422)

    return store_chunks(doc_name, chunks, embedder, pool)
