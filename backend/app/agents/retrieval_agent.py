"""BC9 Retrieval Agent cascade."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.chunking import EmbeddingClient
from app.retrieval.expand_query import ExpansionModelClient, expand_query
from app.retrieval.fetch_page_image import fetch_page_image
from app.retrieval.hybrid_search import hybrid_search
from app.retrieval.models import (
    HybridSearchResult,
    PageImageResult,
    QueryExpansionResult,
    RerankResult,
    RetrievalAgentResult,
    RetrievalCandidate,
)
from app.retrieval.rerank import HostedRerankFn, Reranker, rerank
from app.settings import settings

HybridSearchFn = Callable[..., Awaitable[HybridSearchResult]]
RerankFn = Callable[..., Awaitable[RerankResult]]
ExpandQueryFn = Callable[..., Awaitable[QueryExpansionResult]]
FetchPageImageFn = Callable[..., Awaitable[PageImageResult | None]]


class RetrievalAgent:
    """In-process Retrieval Agent with a bounded low-confidence cascade."""

    def __init__(
        self,
        hybrid_search_fn: HybridSearchFn = hybrid_search,
        rerank_fn: RerankFn = rerank,
        expand_query_fn: ExpandQueryFn = expand_query,
        fetch_page_image_fn: FetchPageImageFn = fetch_page_image,
    ) -> None:
        self._hybrid_search = hybrid_search_fn
        self._rerank = rerank_fn
        self._expand_query = expand_query_fn
        self._fetch_page_image = fetch_page_image_fn

    async def run(
        self,
        db: AsyncSession,
        query: str,
        session_id: UUID | None = None,
        query_audit_log_id: UUID | None = None,
        document_id_filter: list[UUID] | None = None,
        embedding_client: EmbeddingClient | None = None,
        reranker: Reranker | None = None,
        hosted_rerank: HostedRerankFn | None = None,
        expansion_model_client: ExpansionModelClient | None = None,
    ) -> RetrievalAgentResult:
        """Run the retrieval cascade and return final reranked chunks."""
        return await run_retrieval_cascade(
            db=db,
            query=query,
            session_id=session_id,
            query_audit_log_id=query_audit_log_id,
            document_id_filter=document_id_filter,
            embedding_client=embedding_client,
            reranker=reranker,
            hosted_rerank=hosted_rerank,
            expansion_model_client=expansion_model_client,
            hybrid_search_fn=self._hybrid_search,
            rerank_fn=self._rerank,
            expand_query_fn=self._expand_query,
            fetch_page_image_fn=self._fetch_page_image,
        )


async def run_retrieval_cascade(
    db: AsyncSession,
    query: str,
    session_id: UUID | None = None,
    query_audit_log_id: UUID | None = None,
    document_id_filter: list[UUID] | None = None,
    embedding_client: EmbeddingClient | None = None,
    reranker: Reranker | None = None,
    hosted_rerank: HostedRerankFn | None = None,
    expansion_model_client: ExpansionModelClient | None = None,
    hybrid_search_fn: HybridSearchFn = hybrid_search,
    rerank_fn: RerankFn = rerank,
    expand_query_fn: ExpandQueryFn = expand_query,
    fetch_page_image_fn: FetchPageImageFn = fetch_page_image,
) -> RetrievalAgentResult:
    """Run hybrid search, rerank, and bounded expansion when confidence is low."""
    max_iterations = settings.retrieval_agent_max_iterations
    threshold = settings.retrieval_agent_confidence_threshold
    deterministic = await _hybrid_then_rerank(
        db=db,
        query=query,
        document_id_filter=document_id_filter,
        embedding_client=embedding_client,
        reranker=reranker,
        hosted_rerank=hosted_rerank,
        hybrid_search_fn=hybrid_search_fn,
        rerank_fn=rerank_fn,
        session_id=session_id,
        query_audit_log_id=query_audit_log_id,
    )
    hybrid_result, reranked = deterministic
    iterations = 1

    if reranked.top_relevance_score >= threshold:
        return await _build_result(
            db=db,
            hybrid_result=hybrid_result,
            reranked=reranked,
            expanded=False,
            iterations=iterations,
            fallback_used=False,
            fetch_page_image_fn=fetch_page_image_fn,
            session_id=session_id,
            query_audit_log_id=query_audit_log_id,
        )

    try:
        if iterations >= max_iterations:
            return await _build_result(
                db=db,
                hybrid_result=hybrid_result,
                reranked=reranked,
                expanded=False,
                iterations=iterations,
                fallback_used=True,
                fetch_page_image_fn=fetch_page_image_fn,
                session_id=session_id,
                query_audit_log_id=query_audit_log_id,
            )

        expansion = await expand_query_fn(
            query=query,
            reason=f"top_relevance_score={reranked.top_relevance_score:.3f} below threshold={threshold:.3f}",
            model_client=expansion_model_client,
            trace_db=db,
            trace_session_id=session_id,
            trace_query_audit_log_id=query_audit_log_id,
            trace_input={"query": query},
        )
        iterations += 1

        expanded_results: list[HybridSearchResult] = []
        if iterations + 1 > max_iterations:
            raise RuntimeError("retrieval_agent_iteration_bound_exceeded")
        for subquery in expansion.subqueries[:3]:
            expanded_results.append(
                await hybrid_search_fn(
                    db=db,
                    query=subquery,
                    top_k=settings.retrieval_top_k,
                    document_id_filter=document_id_filter,
                    embedding_client=embedding_client,
                    trace_db=db,
                    trace_session_id=session_id,
                    trace_query_audit_log_id=query_audit_log_id,
                    trace_input={"query": subquery, "expanded_from": query},
                )
            )

        merged = merge_candidates_preserving_best_score(
            [hybrid_result, *expanded_results]
            if expansion.fallback_used
            else expanded_results
        )
        expanded_reranked = await rerank_fn(
            query=query,
            candidates=merged,
            top_n=settings.rerank_top_n,
            reranker=reranker,
            hosted_rerank=hosted_rerank,
            trace_db=db,
            trace_session_id=session_id,
            trace_query_audit_log_id=query_audit_log_id,
            trace_input={"query": query, "candidate_count": len(merged)},
        )
        iterations += 1
        return await _build_result(
            db=db,
            hybrid_result=HybridSearchResult(
                candidates=merged,
                top_score=max((candidate.fused_score or 0.0) for candidate in merged) if merged else 0.0,
                rrf_k=settings.rrf_k,
                hybrid_enabled=True,
            ),
            reranked=expanded_reranked,
            expanded=True,
            iterations=iterations,
            fallback_used=False,
            fetch_page_image_fn=fetch_page_image_fn,
            session_id=session_id,
            query_audit_log_id=query_audit_log_id,
        )
    except Exception:
        return await _build_result(
            db=db,
            hybrid_result=hybrid_result,
            reranked=reranked,
            expanded=False,
            iterations=iterations,
            fallback_used=True,
            fetch_page_image_fn=fetch_page_image_fn,
            session_id=session_id,
            query_audit_log_id=query_audit_log_id,
        )


def merge_candidates_preserving_best_score(
    results: list[HybridSearchResult],
) -> list[RetrievalCandidate]:
    """Dedupe candidates by chunk id while preserving the best fused score."""
    candidates_by_id: dict[UUID, RetrievalCandidate] = {}
    for result in results:
        for candidate in result.candidates:
            existing = candidates_by_id.get(candidate.chunk_id)
            if existing is None:
                candidates_by_id[candidate.chunk_id] = candidate.model_copy()
                continue
            best_score = max(existing.fused_score or 0.0, candidate.fused_score or 0.0)
            updates = {"fused_score": best_score}
            if existing.vector_rank is None:
                updates["vector_rank"] = candidate.vector_rank
            if existing.lexical_rank is None:
                updates["lexical_rank"] = candidate.lexical_rank
            candidates_by_id[candidate.chunk_id] = existing.model_copy(update=updates)
    return sorted(
        candidates_by_id.values(),
        key=lambda item: (-(item.fused_score or 0.0), str(item.chunk_id)),
    )


async def _hybrid_then_rerank(
    db: AsyncSession,
    query: str,
    document_id_filter: list[UUID] | None,
    embedding_client: EmbeddingClient | None,
    reranker: Reranker | None,
    hosted_rerank: HostedRerankFn | None,
    hybrid_search_fn: HybridSearchFn,
    rerank_fn: RerankFn,
    session_id: UUID | None,
    query_audit_log_id: UUID | None,
) -> tuple[HybridSearchResult, RerankResult]:
    hybrid_result = await hybrid_search_fn(
        db=db,
        query=query,
        top_k=settings.retrieval_top_k,
        document_id_filter=document_id_filter,
        embedding_client=embedding_client,
        trace_db=db,
        trace_session_id=session_id,
        trace_query_audit_log_id=query_audit_log_id,
        trace_input={"query": query},
    )
    reranked = await rerank_fn(
        query=query,
        candidates=hybrid_result.candidates,
        top_n=settings.rerank_top_n,
        reranker=reranker,
        hosted_rerank=hosted_rerank,
        trace_db=db,
        trace_session_id=session_id,
        trace_query_audit_log_id=query_audit_log_id,
        trace_input={"query": query, "candidate_count": len(hybrid_result.candidates)},
    )
    return hybrid_result, reranked


async def _build_result(
    db: AsyncSession,
    hybrid_result: HybridSearchResult,
    reranked: RerankResult,
    expanded: bool,
    iterations: int,
    fallback_used: bool,
    fetch_page_image_fn: FetchPageImageFn,
    session_id: UUID | None,
    query_audit_log_id: UUID | None,
) -> RetrievalAgentResult:
    page_images: list[PageImageResult] = []
    for candidate in reranked.candidates:
        page_image = await fetch_page_image_fn(
            db=db,
            candidate=candidate,
            trace_db=db,
            trace_session_id=session_id,
            trace_query_audit_log_id=query_audit_log_id,
            trace_input={"chunk_id": str(candidate.chunk_id), "page_number": candidate.page_number},
        )
        if page_image is not None:
            page_images.append(page_image)
    return RetrievalAgentResult(
        chunks=reranked.candidates,
        page_images=page_images,
        expanded=expanded,
        top_score=hybrid_result.top_score,
        top_relevance_score=reranked.top_relevance_score,
        retrieval_mode="agentic_expanded" if expanded else "deterministic",
        iterations=iterations,
        fallback_used=fallback_used,
    )
