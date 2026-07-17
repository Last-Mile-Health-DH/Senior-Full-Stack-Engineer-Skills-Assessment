"""BC5 structure-aware chunking and embedding persistence."""

from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx
import pdfplumber
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.processing import detect_page_structure, resolve_document_pdf_path
from app.models import Chunk, Document

logger = logging.getLogger(__name__)

TOKEN_PATTERN = re.compile(r"\S+")
HEADING_PREFIXES = ("chapter ", "section ", "appendix ")


class EmbeddingClient(Protocol):
    """Provider interface for deterministic tests and hosted embeddings."""

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""


@dataclass(slots=True)
class StructuredBlock:
    """Document block used by the structure-aware chunker."""

    content: str
    page_number: int
    block_type: str
    section_path: str | None = None


@dataclass(slots=True)
class PreparedChunk:
    """Chunk ready for embedding and persistence."""

    chunk_index: int
    content: str
    content_hash: str
    section_path: str | None
    page_number: int | None
    token_count: int


@dataclass(slots=True)
class ChunkingSummary:
    """Persistence summary returned to the worker."""

    chunk_count: int
    embedding_count: int
    embedding_model: str


class HostedEmbeddingClient:
    """Minimal OpenAI/Voyage embedding client using their HTTP APIs."""

    def __init__(
        self,
        model: str | None = None,
        dimensions: int | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.model = model or get_embedding_model()
        self.dimensions = dimensions or get_embedding_dim()
        self.timeout_seconds = timeout_seconds

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if _is_voyage_model(self.model):
            return await self._embed_voyage(texts)
        return await self._embed_openai(texts)

    async def _embed_openai(self, texts: list[str]) -> list[list[float]]:
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not _is_real_key(api_key):
            raise RuntimeError("OPENAI_API_KEY is not configured for hosted embeddings")

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": self.model, "input": texts},
            )
            response.raise_for_status()
            payload = response.json()
        return [item["embedding"] for item in payload["data"]]

    async def _embed_voyage(self, texts: list[str]) -> list[list[float]]:
        api_key = os.getenv("VOYAGE_API_KEY", "")
        if not _is_real_key(api_key):
            raise RuntimeError("VOYAGE_API_KEY is not configured for hosted embeddings")

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                "https://api.voyageai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": self.model, "input": texts},
            )
            response.raise_for_status()
            payload = response.json()
        return [item["embedding"] for item in payload["data"]]


class DeterministicEmbeddingClient:
    """Local deterministic fallback used when hosted provider keys are absent."""

    def __init__(self, dimensions: int | None = None) -> None:
        self.dimensions = dimensions or get_embedding_dim()

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [_hash_embedding(text, self.dimensions) for text in texts]


def get_chunk_size_tokens() -> int:
    """Read configured chunk size."""
    return int(os.getenv("CHUNK_SIZE_TOKENS", "480"))


def get_chunk_overlap_ratio() -> float:
    """Read configured overlap ratio."""
    return float(os.getenv("CHUNK_OVERLAP_RATIO", "0.15"))


def get_embedding_model() -> str:
    """Read configured embedding model."""
    return os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")


def get_embedding_dim() -> int:
    """Read configured embedding vector dimension."""
    return int(os.getenv("EMBEDDING_DIM", "1536"))


def get_embedding_client() -> EmbeddingClient:
    """Return the configured embedding client with a local fallback for dev/test."""
    model = get_embedding_model()
    key_name = "VOYAGE_API_KEY" if _is_voyage_model(model) else "OPENAI_API_KEY"
    if _is_real_key(os.getenv(key_name, "")):
        return HostedEmbeddingClient(model=model)

    logger.warning(
        "embedding.provider_key_missing model=%s key=%s fallback=deterministic",
        model,
        key_name,
    )
    return DeterministicEmbeddingClient()


def chunk_structured_blocks(
    blocks: list[StructuredBlock],
    chunk_size_tokens: int | None = None,
    overlap_ratio: float | None = None,
) -> list[PreparedChunk]:
    """Split structured blocks into token-bounded chunks with section context."""
    chunk_size = chunk_size_tokens or get_chunk_size_tokens()
    overlap = overlap_ratio if overlap_ratio is not None else get_chunk_overlap_ratio()
    overlap_tokens = max(0, min(chunk_size - 1, int(chunk_size * overlap)))

    chunks: list[PreparedChunk] = []
    active_section: str | None = None

    for block in blocks:
        content = _normalize_text(block.content)
        if not content:
            continue

        if block.block_type == "heading":
            active_section = content
            continue

        section_path = block.section_path or active_section
        prefix = f"{section_path}\n\n" if section_path else ""

        if block.block_type == "table":
            chunk_content = f"{prefix}{content}".strip()
            chunks.append(_build_chunk(len(chunks), chunk_content, section_path, block.page_number))
            continue

        prefix_token_count = count_tokens(prefix)
        body_limit = max(1, chunk_size - prefix_token_count)
        for window in _sliding_token_windows(content, body_limit, overlap_tokens):
            chunk_content = f"{prefix}{window}".strip()
            chunks.append(_build_chunk(len(chunks), chunk_content, section_path, block.page_number))

    return chunks


def extract_structured_blocks_from_pdf(pdf_path: Path) -> list[StructuredBlock]:
    """Extract headings, prose, and tables from a PDF for deterministic chunking."""
    blocks: list[StructuredBlock] = []
    active_section: str | None = None

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            structure = detect_page_structure(page, page_index)
            page_text = str(page.extract_text() or "")
            heading_candidates = set(structure.heading_candidates)

            for line in page_text.splitlines():
                normalized = _normalize_text(line)
                if not normalized:
                    continue
                if normalized in heading_candidates or _looks_like_heading(normalized):
                    active_section = normalized
                    blocks.append(
                        StructuredBlock(
                            content=normalized,
                            page_number=page_index,
                            block_type="heading",
                            section_path=active_section,
                        )
                    )
                else:
                    blocks.append(
                        StructuredBlock(
                            content=normalized,
                            page_number=page_index,
                            block_type="paragraph",
                            section_path=active_section,
                        )
                    )

            for table in _extract_tables(page):
                blocks.append(
                    StructuredBlock(
                        content=table,
                        page_number=page_index,
                        block_type="table",
                        section_path=active_section,
                    )
                )

    return blocks


async def prepare_and_persist_document_chunks(
    db: AsyncSession,
    document: Document,
    embedding_client: EmbeddingClient | None = None,
    page_assessments: list[Any] | None = None,
) -> ChunkingSummary:
    """Chunk a document, embed every chunk, and persist rows to ``chunks``."""
    pdf_path = resolve_document_pdf_path(document)
    if page_assessments is not None:
        logger.info(
            "chunking.page_assessments.start document_id=%s pages=%s",
            document.id,
            len(page_assessments),
        )
        blocks = structured_blocks_from_page_assessments(page_assessments)
    else:
        logger.info("chunking.pdf_parse.start document_id=%s path=%s", document.id, pdf_path)
        blocks = extract_structured_blocks_from_pdf(pdf_path)
    logger.info(
        "chunking.pdf_parse.complete document_id=%s blocks=%s",
        document.id,
        len(blocks),
    )

    chunks = chunk_structured_blocks(blocks)
    if not chunks:
        fallback = _fallback_document_text(pdf_path)
        if fallback:
            chunks = chunk_structured_blocks(
                [StructuredBlock(content=fallback, page_number=1, block_type="paragraph")]
            )
    logger.info("chunking.prepare.complete document_id=%s chunks=%s", document.id, len(chunks))

    client = embedding_client or get_embedding_client()
    texts = [chunk.content for chunk in chunks]
    logger.info("embedding.generate.start document_id=%s chunks=%s", document.id, len(texts))
    embeddings = await client.embed_texts(texts)
    validate_embedding_batch(embeddings, expected_count=len(texts), expected_dim=get_embedding_dim())
    logger.info("embedding.generate.complete document_id=%s embeddings=%s", document.id, len(embeddings))

    logger.info("chunks.db.transaction.start document_id=%s", document.id)
    await db.execute(delete(Chunk).where(Chunk.document_id == document.id))
    for chunk, embedding in zip(chunks, embeddings, strict=True):
        await db.execute(
            text(
                """
                INSERT INTO chunks (
                    document_id,
                    chunk_index,
                    content,
                    content_hash,
                    section_path,
                    page_number,
                    token_count,
                    embedding,
                    embedding_model
                )
                VALUES (
                    :document_id,
                    :chunk_index,
                    :content,
                    :content_hash,
                    :section_path,
                    :page_number,
                    :token_count,
                    CAST(:embedding AS vector),
                    :embedding_model
                )
                """
            ),
            {
                "document_id": document.id,
                "chunk_index": chunk.chunk_index,
                "content": chunk.content,
                "content_hash": chunk.content_hash,
                "section_path": chunk.section_path,
                "page_number": chunk.page_number,
                "token_count": chunk.token_count,
                "embedding": _vector_literal(embedding),
                "embedding_model": get_embedding_model(),
            },
        )
    logger.info("chunks.db.transaction.prepared document_id=%s rows=%s", document.id, len(chunks))

    return ChunkingSummary(
        chunk_count=len(chunks),
        embedding_count=len(embeddings),
        embedding_model=get_embedding_model(),
    )


def structured_blocks_from_page_assessments(page_assessments: list[Any]) -> list[StructuredBlock]:
    """Convert BC6 page assessments into deterministic chunking blocks."""
    blocks: list[StructuredBlock] = []
    active_section: str | None = None
    for assessment in page_assessments:
        page_number = int(getattr(assessment, "page_number"))
        heading_candidates = list(getattr(assessment, "heading_candidates", []) or [])
        text_value = str(getattr(assessment, "text", "") or "")

        for heading in heading_candidates:
            normalized_heading = _normalize_text(str(heading))
            if normalized_heading:
                active_section = normalized_heading
                blocks.append(
                    StructuredBlock(
                        content=normalized_heading,
                        page_number=page_number,
                        block_type="heading",
                        section_path=active_section,
                    )
                )

        for line in text_value.splitlines():
            normalized_line = _normalize_text(line)
            if not normalized_line:
                continue
            if normalized_line in heading_candidates or _looks_like_heading(normalized_line):
                active_section = normalized_line
                blocks.append(
                    StructuredBlock(
                        content=normalized_line,
                        page_number=page_number,
                        block_type="heading",
                        section_path=active_section,
                    )
                )
            else:
                blocks.append(
                    StructuredBlock(
                        content=normalized_line,
                        page_number=page_number,
                        block_type="paragraph",
                        section_path=active_section,
                    )
                )

        if getattr(assessment, "has_table", False):
            table_text = _normalize_text(text_value)
            if table_text:
                blocks.append(
                    StructuredBlock(
                        content=table_text,
                        page_number=page_number,
                        block_type="table",
                        section_path=active_section,
                    )
                )

    return blocks


def validate_embedding_batch(
    embeddings: list[list[float]],
    expected_count: int,
    expected_dim: int,
) -> None:
    """Fail fast if provider output cannot fit the configured pgvector column."""
    if len(embeddings) != expected_count:
        raise ValueError(
            f"Embedding count mismatch: expected {expected_count}, got {len(embeddings)}"
        )
    for index, embedding in enumerate(embeddings):
        if len(embedding) != expected_dim:
            raise ValueError(
                f"Embedding dimension mismatch at index {index}: "
                f"expected {expected_dim}, got {len(embedding)}"
            )


def count_tokens(text_value: str) -> int:
    """Approximate token count with whitespace tokens for deterministic splitting."""
    return len(TOKEN_PATTERN.findall(text_value))


def _build_chunk(
    index: int,
    content: str,
    section_path: str | None,
    page_number: int | None,
) -> PreparedChunk:
    return PreparedChunk(
        chunk_index=index,
        content=content,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        section_path=section_path,
        page_number=page_number,
        token_count=count_tokens(content),
    )


def _sliding_token_windows(
    content: str,
    chunk_size: int,
    overlap_tokens: int,
) -> list[str]:
    tokens = TOKEN_PATTERN.findall(content)
    if not tokens:
        return []

    windows: list[str] = []
    start = 0
    step = max(1, chunk_size - overlap_tokens)
    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        windows.append(" ".join(tokens[start:end]))
        if end == len(tokens):
            break
        start += step
    return windows


def _extract_tables(page: Any) -> list[str]:
    try:
        raw_tables = page.extract_tables() or []
    except Exception:
        return []
    return [_table_to_markdown(table) for table in raw_tables if table]


def _table_to_markdown(table: list[list[Any]]) -> str:
    rows = [[_normalize_text(str(cell or "")) for cell in row] for row in table if row]
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]
    header = padded[0]
    separator = ["---"] * width
    body = padded[1:] or [[""] * width]
    markdown_rows = [header, separator, *body]
    return "\n".join("| " + " | ".join(row) + " |" for row in markdown_rows)


def _looks_like_heading(line: str) -> bool:
    letters = [character for character in line if character.isalpha()]
    uppercase_ratio = (
        sum(1 for character in letters if character.isupper()) / len(letters)
        if letters
        else 0.0
    )
    return uppercase_ratio >= 0.65 or line.lower().startswith(HEADING_PREFIXES)


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().split())


def _fallback_document_text(pdf_path: Path) -> str:
    try:
        with pdfplumber.open(pdf_path) as pdf:
            return "\n".join(str(page.extract_text() or "") for page in pdf.pages).strip()
    except Exception:
        return ""


def _vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in embedding) + "]"


def _hash_embedding(text_value: str, dimensions: int) -> list[float]:
    digest = hashlib.sha256(text_value.encode("utf-8")).digest()
    values: list[float] = []
    while len(values) < dimensions:
        for byte in digest:
            values.append((byte / 255.0) - 0.5)
            if len(values) == dimensions:
                break
        digest = hashlib.sha256(digest).digest()
    return values


def _is_voyage_model(model: str) -> bool:
    return model.lower().startswith("voyage")


def _is_real_key(value: str) -> bool:
    stripped = value.strip()
    return bool(stripped and not stripped.startswith("your-") and "api-key-here" not in stripped)
