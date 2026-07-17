from __future__ import annotations

from uuid import UUID

import pytest

from app.retrieval.models import RerankResult, RetrievalCandidate
from app.retrieval.rerank import rerank
from app.settings import settings


class FakeReranker:
    def __init__(self, logits: list[float]) -> None:
        self.logits = logits
        self.pairs_seen: list[tuple[str, str]] = []

    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        self.pairs_seen = pairs
        return self.logits


@pytest.mark.asyncio
async def test_rerank_empty_candidates_returns_zero() -> None:
    result = await rerank("malaria", [], reranker=FakeReranker([]))

    assert result.top_relevance_score == 0.0
    assert result.candidates == []
    assert result.all_scores == []


@pytest.mark.asyncio
async def test_rerank_sigmoid_scores_are_bounded_and_ordered() -> None:
    low = _candidate("00000000-0000-0000-0000-000000000001", "irrelevant nutrition text")
    high = _candidate("00000000-0000-0000-0000-000000000002", "malaria dosage protocol")
    fake = FakeReranker([-4.0, 4.0])

    result = await rerank("malaria dosage", [low, high], top_n=2, reranker=fake)

    assert [candidate.chunk_id for candidate in result.candidates] == [high.chunk_id, low.chunk_id]
    assert 0.0 <= result.top_relevance_score <= 1.0
    assert result.top_relevance_score > 0.98
    assert result.candidates[0].rerank_logit == 4.0
    assert result.candidates[0].rerank_score == pytest.approx(result.top_relevance_score)
    assert fake.pairs_seen == [
        ("malaria dosage", "irrelevant nutrition text"),
        ("malaria dosage", "malaria dosage protocol"),
    ]


@pytest.mark.asyncio
async def test_rerank_limits_top_n() -> None:
    candidates = [
        _candidate("00000000-0000-0000-0000-000000000001", "first"),
        _candidate("00000000-0000-0000-0000-000000000002", "second"),
        _candidate("00000000-0000-0000-0000-000000000003", "third"),
    ]

    result = await rerank("query", candidates, top_n=1, reranker=FakeReranker([0.0, 3.0, 1.0]))

    assert len(result.candidates) == 1
    assert result.candidates[0].content == "second"
    assert len(result.all_scores) == 3


@pytest.mark.asyncio
async def test_rerank_uses_hosted_strategy_when_provider_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "rerank_provider", "hosted-test")
    candidate = _candidate("00000000-0000-0000-0000-000000000004", "hosted")

    def fake_hosted(query: str, candidates: list[RetrievalCandidate], top_n: int) -> RerankResult:
        return RerankResult(
            candidates=candidates[:top_n],
            top_relevance_score=0.75,
            all_scores=[0.75],
            raw_logits=[1.1],
            duration_ms=1,
            provider=f"hosted:{query}",
        )

    try:
        result = await rerank("hosted query", [candidate], top_n=1, hosted_rerank=fake_hosted)
    finally:
        monkeypatch.setattr(settings, "rerank_provider", "")

    assert result.provider == "hosted:hosted query"
    assert result.top_relevance_score == 0.75


@pytest.mark.asyncio
async def test_rerank_requires_hosted_adapter_when_provider_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "rerank_provider", "hosted-test")
    try:
        with pytest.raises(RuntimeError, match="no hosted reranker"):
            await rerank("query", [_candidate("00000000-0000-0000-0000-000000000005", "content")])
    finally:
        monkeypatch.setattr(settings, "rerank_provider", "")


def _candidate(chunk_id: str, content: str) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=UUID(chunk_id),
        document_id=UUID("10000000-0000-0000-0000-000000000000"),
        document_filename="test.pdf",
        document_status="indexed",
        document_metadata={},
        content=content,
        page_number=1,
        section_path="TEST",
    )
