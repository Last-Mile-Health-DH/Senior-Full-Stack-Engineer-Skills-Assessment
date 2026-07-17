"""Typed retrieval and reranking contracts."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class RetrievalCandidate(BaseModel):
    """One chunk candidate returned by vector, lexical, hybrid, or rerank."""

    chunk_id: UUID
    document_id: UUID
    document_filename: str
    document_status: str
    document_metadata: dict[str, object] = Field(default_factory=dict)
    content: str
    page_number: int | None = None
    section_path: str | None = None
    vector_rank: int | None = None
    lexical_rank: int | None = None
    fused_score: float | None = None
    vector_distance: float | None = None
    lexical_score: float | None = None
    rerank_logit: float | None = None
    rerank_score: float | None = None


class HybridSearchResult(BaseModel):
    """Hybrid retrieval output.

    ``top_score`` is a raw RRF fusion and ordering signal only. For two ranked
    lists it is bounded by ``2 / (rrf_k + 1)`` and must never be used as a
    0-1 confidence score; BC8's reranker owns confidence.
    """

    candidates: list[RetrievalCandidate]
    top_score: float
    rrf_k: int
    hybrid_enabled: bool


class RerankResult(BaseModel):
    """Reranked candidates plus bounded relevance metadata."""

    candidates: list[RetrievalCandidate]
    top_relevance_score: float
    all_scores: list[float]
    raw_logits: list[float]
    duration_ms: int
    provider: str


class QueryExpansionResult(BaseModel):
    """Strict query expansion output used by the Retrieval Agent."""

    subqueries: list[str] = Field(min_length=1, max_length=3)
    reason: str = ""
    fallback_used: bool = False


class PageImageResult(BaseModel):
    """Internal-only page image metadata for a final retrieved chunk."""

    chunk_id: UUID
    document_id: UUID
    page_number: int
    storage_ref: str
    has_table: bool = False
    has_figure: bool = False


class RetrievalAgentResult(BaseModel):
    """Final Retrieval Agent output consumed by the Orchestrator."""

    chunks: list[RetrievalCandidate]
    page_images: list[PageImageResult] = Field(default_factory=list)
    expanded: bool = False
    top_score: float = 0.0
    top_relevance_score: float = 0.0
    retrieval_mode: str = "deterministic"
    iterations: int = 1
    fallback_used: bool = False
