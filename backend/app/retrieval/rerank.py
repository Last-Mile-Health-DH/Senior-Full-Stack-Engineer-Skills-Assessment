"""BC8 local/hosted reranking with bounded relevance scores."""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence
from typing import Protocol

from app.agents.tracing import traced
from app.retrieval.models import RerankResult, RetrievalCandidate
from app.settings import settings


class Reranker(Protocol):
    """Minimal cross-encoder-like interface."""

    def predict(self, pairs: Sequence[tuple[str, str]]) -> Sequence[float]:
        """Return one raw relevance logit per query/candidate pair."""


HostedRerankFn = Callable[[str, list[RetrievalCandidate], int], RerankResult]

_LOCAL_RERANKER: Reranker | None = None


@traced(agent_name="retrieval_agent")
async def rerank(
    query: str,
    candidates: list[RetrievalCandidate],
    top_n: int | None = None,
    reranker: Reranker | None = None,
    hosted_rerank: HostedRerankFn | None = None,
) -> RerankResult:
    """Rerank candidates and return a sigmoid-bounded confidence signal."""
    limit = top_n or settings.rerank_top_n
    if settings.rerank_provider:
        if hosted_rerank is None:
            raise RuntimeError("RERANK_PROVIDER is configured but no hosted reranker is available")
        return hosted_rerank(query, candidates, limit)
    return _local_rerank(query, candidates, limit, reranker or get_local_reranker())


def _local_rerank(
    query: str,
    candidates: list[RetrievalCandidate],
    top_n: int,
    reranker: Reranker,
) -> RerankResult:
    start = time.monotonic()
    if not candidates:
        return RerankResult(
            candidates=[],
            top_relevance_score=0.0,
            all_scores=[],
            raw_logits=[],
            duration_ms=0,
            provider="local",
        )

    pairs = [(query, candidate.content) for candidate in candidates]
    logits = [float(value) for value in reranker.predict(pairs)]
    if len(logits) != len(candidates):
        raise ValueError(f"Reranker returned {len(logits)} scores for {len(candidates)} candidates")

    scored: list[tuple[RetrievalCandidate, float, float]] = []
    for candidate, logit in zip(candidates, logits, strict=True):
        score = _sigmoid(logit)
        scored_candidate = candidate.model_copy(
            update={"rerank_logit": logit, "rerank_score": score}
        )
        scored.append((scored_candidate, logit, score))

    scored.sort(key=lambda item: item[2], reverse=True)
    duration_ms = int((time.monotonic() - start) * 1000)
    return RerankResult(
        candidates=[candidate for candidate, _, _ in scored[:top_n]],
        top_relevance_score=scored[0][2],
        all_scores=[score for _, _, score in scored],
        raw_logits=[logit for _, logit, _ in scored],
        duration_ms=duration_ms,
        provider="local",
    )


def get_local_reranker() -> Reranker:
    """Load the local cross-encoder lazily once per process."""
    global _LOCAL_RERANKER
    if _LOCAL_RERANKER is None:
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is required for local reranking; "
                "inject a reranker in tests or configure RERANK_PROVIDER"
            ) from exc
        _LOCAL_RERANKER = CrossEncoder(settings.reranker_model)
    return _LOCAL_RERANKER


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)
