"""BC5 structure-aware chunking and embedding persistence."""

from __future__ import annotations

import hashlib
import logging
import math
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


class GeminiEmbeddingClient:
    """Google Generative Language embeddings.

    `gemini-embedding-001` is natively 3072-dimensional but supports Matryoshka
    truncation, so `outputDimensionality` is used to request exactly `EMBEDDING_DIM`
    (1536). That is what lets Gemini be swapped in without a schema migration — the
    pgvector column is fixed-width, so a model whose dimension cannot be set would
    require re-creating the column and re-indexing the whole corpus.

    Truncated Matryoshka vectors are NOT unit-length, so they are re-normalized here.
    Retrieval uses cosine distance, which normalizes internally, but the semantic cache
    compares raw similarity values — leaving them unnormalized would make its threshold
    mean something different for Gemini than for OpenAI.
    """

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(
        self,
        model: str | None = None,
        dimensions: int | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self.model = model or get_embedding_model()
        self.dimensions = dimensions or get_embedding_dim()
        self.timeout_seconds = timeout_seconds

    # `batchEmbedContents` rejects more than 100 requests in one call with a bare 400, and —
    # critically on a free tier — every item in the batch counts as one request against the
    # per-minute quota. A batch at the 100 ceiling therefore burns a whole ~100 req/min free
    # allowance in one call and 429s. The batch size and an inter-batch pace are read from
    # settings so the free tier stays under quota while a paid tier can turn pacing off.
    @property
    def _batch_limit(self) -> int:
        from app.settings import settings

        return max(1, min(settings.embedding_batch_limit, 100))

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        import asyncio

        from app.settings import settings

        api_key = os.getenv("GEMINI_API_KEY", "")
        if not _is_real_key(api_key):
            raise RuntimeError("GEMINI_API_KEY is not configured for hosted embeddings")

        batch_limit = self._batch_limit
        rpm = settings.embedding_requests_per_minute
        model_path = f"models/{self.model}"
        vectors: list[list[float]] = []
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            batches = list(range(0, len(texts), batch_limit))
            for index, start in enumerate(batches):
                window = texts[start : start + batch_limit]
                payload = {
                    "requests": [
                        {
                            "model": model_path,
                            "content": {"parts": [{"text": text}]},
                            "outputDimensionality": self.dimensions,
                            # Chunks and queries share one interface, so a symmetric task
                            # type is used rather than silently mislabelling one side.
                            "taskType": "SEMANTIC_SIMILARITY",
                        }
                        for text in window
                    ]
                }
                body = await _gemini_post_with_retry(
                    client,
                    f"{self.BASE_URL}/{model_path}:batchEmbedContents",
                    api_key,
                    payload,
                )
                vectors.extend(_l2_normalize(item["values"]) for item in body["embeddings"])
                # Pace the next batch so the rolling request rate stays under the free-tier
                # quota. Skip the pause after the final batch — nothing follows it.
                if rpm > 0 and index < len(batches) - 1:
                    await asyncio.sleep((len(window) / rpm) * 60.0)
        return vectors


class DeterministicEmbeddingClient:
    """Local deterministic fallback used when hosted provider keys are absent."""

    def __init__(self, dimensions: int | None = None) -> None:
        self.dimensions = dimensions or get_embedding_dim()

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [_hash_embedding(text, self.dimensions) for text in texts]


async def _embed_with_reuse(
    db: AsyncSession,
    chunks: list[PreparedChunk],
    client: EmbeddingClient,
) -> list[list[float]]:
    """Embed only the chunks whose text has never been embedded before.

    Document-level dedup (SHA-256 of the file bytes) already stops the *same file* being
    ingested twice. It cannot help when the same content arrives as different bytes — a
    re-export, a re-scan, the same protocol inside a larger bundle, the same boilerplate
    appendix in three different guidelines. Those produce byte-different files whose chunks
    are textually identical, and every one of those chunks would otherwise be embedded and
    paid for again.

    `chunks.content_hash` is the dedup key. An existing vector for the same text is reused
    verbatim, which is safe because it is the same text embedded by the same model — rows
    are scoped to `embedding_model`, so a vector from a different model is never reused.

    Reuse happens across documents and therefore across sessions: the corpus is shared, so
    a chunk embedded for one user's upload is reused for everyone.
    """
    if not chunks:
        return []

    model = get_embedding_model()
    hashes = [chunk.content_hash for chunk in chunks]

    rows = (
        await db.execute(
            text(
                """
                SELECT DISTINCT ON (content_hash) content_hash, embedding
                FROM chunks
                WHERE content_hash = ANY(:hashes)
                  AND embedding_model = :model
                  AND embedding IS NOT NULL
                """
            ),
            {"hashes": hashes, "model": model},
        )
    ).mappings().all()
    cached = {row["content_hash"]: _parse_vector(row["embedding"]) for row in rows}

    # Deduplicate WITHIN the request too. A document repeats content (a running header, a
    # boilerplate warning on every page); sending each copy would pay for the same text
    # several times in a single ingestion.
    pending: dict[str, PreparedChunk] = {}
    for chunk in chunks:
        if chunk.content_hash not in cached:
            pending.setdefault(chunk.content_hash, chunk)

    logger.info(
        "embedding.reuse total=%s reused=%s embedded=%s model=%s",
        len(chunks),
        len(chunks) - len(pending),
        len(pending),
        model,
    )

    if pending:
        to_embed = list(pending.values())
        fresh = await client.embed_texts([chunk.content for chunk in to_embed])
        for chunk, vector in zip(to_embed, fresh, strict=True):
            cached[chunk.content_hash] = vector

    return [cached[chunk.content_hash] for chunk in chunks]


def _parse_vector(value: object) -> list[float]:
    """pgvector comes back as a bracketed string over the raw driver."""
    if isinstance(value, (list, tuple)):
        return [float(item) for item in value]
    return [float(part) for part in str(value).strip("[]").split(",") if part]


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


def embedding_key_name(model: str) -> str:
    """Which provider key a given embedding model needs."""
    if _is_voyage_model(model):
        return "VOYAGE_API_KEY"
    if _is_gemini_model(model):
        return "GEMINI_API_KEY"
    return "OPENAI_API_KEY"


def get_embedding_client() -> EmbeddingClient:
    """Route to the cheapest configured embedding provider; degrade if there is none.

    The fallback is deliberate — the stack must run with no keys — but it is NOT the
    product: hash-based vectors make semantic search meaningless, so only the lexical half
    of hybrid retrieval does anything. `/chat` therefore returns a `model_status` telling
    the user their search is limited, rather than letting them judge retrieval quality on a
    path they did not know they were on.

    An explicitly pinned EMBEDDING_MODEL wins over routing: unlike a generation model, the
    embedding model cannot be swapped freely — the pgvector column is fixed-width and the
    stored vectors were produced by one specific model, so silently routing to a different
    one would compare vectors across models.
    """
    from app.core.model_router import is_real_key, resolve_embedding

    model = get_embedding_model()
    key_name = embedding_key_name(model)

    # A pinned model whose key is present always wins — see docstring.
    if is_real_key(os.getenv(key_name, "")):
        if _is_gemini_model(model):
            return GeminiEmbeddingClient(model=model)
        return HostedEmbeddingClient(model=model)

    routed = resolve_embedding()
    if routed is not None:
        logger.info("embedding.routed provider=%s model=%s", routed.provider, routed.model)
        if routed.provider == "gemini":
            return GeminiEmbeddingClient(model=routed.model)
        return HostedEmbeddingClient(model=routed.model)

    logger.warning(
        "embedding.no_provider_configured model=%s key=%s fallback=deterministic "
        "(semantic search is effectively disabled)",
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

    # Choose HOW to chunk from what the document actually is, rather than running one
    # strategy over everything. See documents/chunk_strategy.py for the reasoning.
    from app.documents.chunk_strategy import (
        ChunkStrategy,
        flatten_for_fixed_size,
        profile_blocks,
        select_strategy,
    )

    plan = select_strategy(
        profile_blocks(blocks, document.page_count or 0),
        default_overlap=get_chunk_overlap_ratio(),
    )
    logger.info(
        "chunking.strategy document_id=%s strategy=%s reason=%s",
        document.id,
        plan.strategy.value,
        plan.reason,
    )

    blocks_for_chunking = (
        blocks if plan.strategy is ChunkStrategy.STRUCTURE_AWARE else flatten_for_fixed_size(blocks)
    )
    chunks = chunk_structured_blocks(blocks_for_chunking, overlap_ratio=plan.overlap_ratio)
    if not chunks:
        fallback = _fallback_document_text(pdf_path)
        if fallback:
            chunks = chunk_structured_blocks(
                [StructuredBlock(content=fallback, page_number=1, block_type="paragraph")],
                overlap_ratio=plan.overlap_ratio,
            )
    logger.info("chunking.prepare.complete document_id=%s chunks=%s", document.id, len(chunks))

    # Record the decision twice, on purpose:
    #  - on the document, so a reviewer can see which strategy it got without a join;
    #  - in the agent trace, so the ingestion chain replays alongside every other decision.
    document.metadata_ = {**(document.metadata_ or {}), **plan.as_metadata()}

    from app.agents.tracing import record_decision

    await record_decision(
        db,
        agent_id="ingestion_agent",
        decision="chunk_strategy_selected",
        detail=plan.as_metadata(),
        document_id=document.id,
    )

    client = embedding_client or get_embedding_client()
    embeddings = await _embed_with_reuse(db, chunks, client)
    validate_embedding_batch(
        embeddings, expected_count=len(chunks), expected_dim=get_embedding_dim()
    )

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


async def _gemini_post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    api_key: str,
    payload: dict[str, Any],
    max_attempts: int = 7,
) -> dict[str, Any]:
    """POST to Gemini, retrying transient rate limits, 5xx, and network errors with backoff.

    Gemini's free tier limits requests per minute, and a 659-page corpus produces many
    embedding batches. Without this, the first 429 failed the whole document — which is
    exactly what stalled ingestion. A rate limit is transient, so it is retried (honoring
    Retry-After when present) rather than treated as a permanent error. A 4xx that is not 429
    is a real client error and is raised immediately.

    Transient transport errors are retried too. A long ingestion run makes hundreds of calls,
    and a single DNS/connection blip (`No address associated with hostname`, a read timeout)
    is not a status code — it is raised from `client.post` — so it would otherwise kill the
    whole document even though the network recovers a second later. This is a real failure
    mode on WSL2/Docker networking under load.

    The backoff climbs to 60s and runs enough attempts (2+4+8+16+32+60 ≈ 122s of waiting)
    that a request stuck behind a per-minute quota can wait the window out instead of giving
    up inside it — the failure mode that a 5-attempt/30s cap could not recover from.
    """
    import asyncio

    delay = 2.0
    for attempt in range(1, max_attempts + 1):
        try:
            response = await client.post(url, headers={"x-goog-api-key": api_key}, json=payload)
        except httpx.TransportError as exc:
            # Connect/DNS/read-timeout errors are transient; retry them like a 5xx.
            if attempt == max_attempts:
                raise
            logger.warning(
                "gemini.transport_error type=%s attempt=%s/%s sleeping=%.1fs",
                type(exc).__name__,
                attempt,
                max_attempts,
                delay,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60.0)
            continue
        if response.status_code == 429 or response.status_code >= 500:
            if attempt == max_attempts:
                response.raise_for_status()
            wait = _retry_after_seconds(response) or delay
            logger.warning(
                "gemini.rate_limited status=%s attempt=%s/%s sleeping=%.1fs",
                response.status_code,
                attempt,
                max_attempts,
                wait,
            )
            await asyncio.sleep(wait)
            delay = min(delay * 2, 60.0)
            continue
        response.raise_for_status()
        return response.json()
    raise RuntimeError("unreachable")  # pragma: no cover


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Read a Retry-After header, tolerating the RetryInfo the API sometimes returns."""
    header = response.headers.get("retry-after")
    if header:
        try:
            return float(header)
        except ValueError:
            return None
    return None


def _is_voyage_model(model: str) -> bool:
    return model.lower().startswith("voyage")


def _is_gemini_model(model: str) -> bool:
    return model.lower().startswith(("gemini", "text-embedding-004", "models/gemini"))


def _l2_normalize(values: list[float]) -> list[float]:
    """Matryoshka-truncated Gemini vectors are not unit-length; retrieval assumes they are."""
    magnitude = math.sqrt(sum(value * value for value in values))
    if magnitude == 0.0:
        return values
    return [value / magnitude for value in values]


def _is_real_key(value: str) -> bool:
    stripped = value.strip()
    return bool(stripped and not stripped.startswith("your-") and "api-key-here" not in stripped)
