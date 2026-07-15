from __future__ import annotations

from uuid import UUID

import pytest

from app.agents.retrieval_agent import (
    merge_candidates_preserving_best_score,
    run_retrieval_cascade,
)
from app.main import app
from app.retrieval.expand_query import parse_expansion_response
from app.retrieval.models import (
    HybridSearchResult,
    QueryExpansionResult,
    RerankResult,
    RetrievalCandidate,
)
from app.settings import settings


@pytest.mark.asyncio
async def test_high_confidence_skips_expansion() -> None:
    calls: list[str] = []

    async def fake_expand_query(**kwargs: object) -> QueryExpansionResult:
        calls.append("expand")
        return QueryExpansionResult(subqueries=["expanded"])

    result = await run_retrieval_cascade(
        db=object(),  # type: ignore[arg-type]
        query="malaria dosing",
        hybrid_search_fn=_hybrid_fn([_candidate("00000000-0000-0000-0000-000000000001", 0.01)]),
        rerank_fn=_rerank_fn([0.90]),
        expand_query_fn=fake_expand_query,
        fetch_page_image_fn=_no_image,
    )

    assert result.expanded is False
    assert result.fallback_used is False
    assert calls == []


@pytest.mark.asyncio
async def test_low_confidence_triggers_expansion() -> None:
    hybrid_calls: list[str] = []

    async def fake_hybrid_search(**kwargs: object) -> HybridSearchResult:
        query = str(kwargs["query"])
        hybrid_calls.append(query)
        suffix = "2" if query == "expanded query" else "1"
        return HybridSearchResult(
            candidates=[_candidate(f"00000000-0000-0000-0000-00000000000{suffix}", 0.02)],
            top_score=0.02,
            rrf_k=60,
            hybrid_enabled=True,
        )

    async def fake_expand_query(**kwargs: object) -> QueryExpansionResult:
        return QueryExpansionResult(subqueries=["expanded query"])

    result = await run_retrieval_cascade(
        db=object(),  # type: ignore[arg-type]
        query="ambiguous",
        hybrid_search_fn=fake_hybrid_search,
        rerank_fn=_rerank_sequence([[0.20], [0.80]]),
        expand_query_fn=fake_expand_query,
        fetch_page_image_fn=_no_image,
    )

    assert result.expanded is True
    assert result.retrieval_mode == "agentic_expanded"
    assert hybrid_calls == ["ambiguous", "expanded query"]


@pytest.mark.asyncio
async def test_gate_uses_top_relevance_score_not_hybrid_top_score() -> None:
    expanded = False

    async def fake_expand_query(**kwargs: object) -> QueryExpansionResult:
        nonlocal expanded
        expanded = True
        return QueryExpansionResult(subqueries=["expanded"])

    result = await run_retrieval_cascade(
        db=object(),  # type: ignore[arg-type]
        query="rrf high confidence low",
        hybrid_search_fn=_hybrid_fn([_candidate("00000000-0000-0000-0000-000000000001", 0.99)], top_score=0.99),
        rerank_fn=_rerank_sequence([[0.20], [0.80]]),
        expand_query_fn=fake_expand_query,
        fetch_page_image_fn=_no_image,
    )

    assert expanded is True
    assert result.expanded is True


def test_malformed_expansion_output_falls_back_to_original_query() -> None:
    parsed = parse_expansion_response("not json", original_query="original question")

    assert parsed.fallback_used is True
    assert parsed.subqueries == ["original question"]


def test_merge_dedup_keeps_best_fused_score() -> None:
    chunk_id = "00000000-0000-0000-0000-000000000001"
    result = merge_candidates_preserving_best_score(
        [
            HybridSearchResult(candidates=[_candidate(chunk_id, 0.01)], top_score=0.01, rrf_k=60, hybrid_enabled=True),
            HybridSearchResult(candidates=[_candidate(chunk_id, 0.03)], top_score=0.03, rrf_k=60, hybrid_enabled=True),
        ]
    )

    assert len(result) == 1
    assert result[0].fused_score == pytest.approx(0.03)


@pytest.mark.asyncio
async def test_iteration_bound_falls_back_to_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "retrieval_agent_max_iterations", 2)

    result = await run_retrieval_cascade(
        db=object(),  # type: ignore[arg-type]
        query="low confidence",
        hybrid_search_fn=_hybrid_fn([_candidate("00000000-0000-0000-0000-000000000001", 0.01)]),
        rerank_fn=_rerank_fn([0.20]),
        expand_query_fn=_expand_fn(["expanded"]),
        fetch_page_image_fn=_no_image,
    )

    assert result.expanded is False
    assert result.fallback_used is True


def test_no_public_page_image_route_exists() -> None:
    paths = {route.path for route in app.routes}

    assert not any("page-image" in path or "page_images" in path or "page-images" in path for path in paths)


@pytest.mark.asyncio
async def test_trace_context_is_passed_to_supported_tools() -> None:
    seen: list[dict[str, object]] = []

    async def traced_hybrid(**kwargs: object) -> HybridSearchResult:
        seen.append(kwargs)
        return HybridSearchResult(candidates=[_candidate("00000000-0000-0000-0000-000000000001", 0.01)], top_score=0.01, rrf_k=60, hybrid_enabled=True)

    result = await run_retrieval_cascade(
        db="trace-db",  # type: ignore[arg-type]
        query="trace",
        session_id=UUID("11111111-1111-1111-1111-111111111111"),
        query_audit_log_id=UUID("22222222-2222-2222-2222-222222222222"),
        hybrid_search_fn=traced_hybrid,
        rerank_fn=_rerank_fn([0.90]),
        fetch_page_image_fn=_no_image,
    )

    assert result.expanded is False
    assert seen[0]["trace_db"] == "trace-db"
    assert seen[0]["trace_session_id"] == UUID("11111111-1111-1111-1111-111111111111")
    assert seen[0]["trace_query_audit_log_id"] == UUID("22222222-2222-2222-2222-222222222222")


def _candidate(chunk_id: str, fused_score: float) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=UUID(chunk_id),
        document_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        document_filename="source.pdf",
        document_status="indexed",
        content="malaria dosing protocol",
        page_number=1,
        fused_score=fused_score,
    )


def _hybrid_fn(candidates: list[RetrievalCandidate], top_score: float = 0.02):
    async def fake_hybrid_search(**kwargs: object) -> HybridSearchResult:
        return HybridSearchResult(candidates=candidates, top_score=top_score, rrf_k=60, hybrid_enabled=True)

    return fake_hybrid_search


def _rerank_fn(scores: list[float]):
    async def fake_rerank(**kwargs: object) -> RerankResult:
        candidates = list(kwargs["candidates"])
        updated = [
            candidate.model_copy(update={"rerank_score": score})
            for candidate, score in zip(candidates, scores, strict=False)
        ]
        return RerankResult(
            candidates=updated,
            top_relevance_score=max(scores) if scores else 0.0,
            all_scores=scores,
            raw_logits=scores,
            duration_ms=0,
            provider="fake",
        )

    return fake_rerank


def _rerank_sequence(score_sets: list[list[float]]):
    calls = {"count": 0}

    async def fake_rerank(**kwargs: object) -> RerankResult:
        index = min(calls["count"], len(score_sets) - 1)
        calls["count"] += 1
        return await _rerank_fn(score_sets[index])(**kwargs)

    return fake_rerank


def _expand_fn(subqueries: list[str]):
    async def fake_expand(**kwargs: object) -> QueryExpansionResult:
        return QueryExpansionResult(subqueries=subqueries)

    return fake_expand


async def _no_image(**kwargs: object) -> None:
    return None
