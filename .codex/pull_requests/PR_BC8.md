# Pull Request: [BC8] - Reranking with Bounded Confidence

## Executive Summary
BC8 adds the reranking layer that consumes BC7 candidates and produces the bounded `top_relevance_score` BC9 will use for retrieval confidence gating. The default path is a local cross-encoder loaded lazily once per process, with deterministic tests using injected fake rerankers and a hosted-provider escape hatch behind the same typed contract.

## Changes Introduced

### Reranking Runtime
- Added `backend/app/retrieval/rerank.py` with one public `rerank(query, candidates, top_n)` entry point.
- Added `RerankResult` metadata carrying reranked candidates, sigmoid scores, raw logits, duration, and provider.
- Converted raw cross-encoder logits through a numerically stable sigmoid so `top_relevance_score` is always bounded in `[0, 1]`.
- Returned an empty result with `top_relevance_score=0.0` for empty candidate lists.
- Added a lazy local CrossEncoder singleton through `get_local_reranker`.
- Added optional hosted-reranker dispatch through `RERANK_PROVIDER`.
- Wrapped rerank with the retrieval-agent tracing decorator; persisted trace rows are written when later callers pass trace context.

### Configuration
- Added `RERANK_TOP_N`, `RERANKER_MODEL`, and `RERANK_PROVIDER`.
- Added the pinned `sentence-transformers` backend dependency for the default local CrossEncoder path.

### Tests
- Added `backend/app/tests/test_rerank.py` covering empty input, sigmoid score bounds, score ordering, top-n limiting, hosted-provider strategy selection, and the missing-hosted-adapter error path.

### Documentation
- Updated `plan.md`, `tests-README.md`, and the BC5-BC10 batch plan with BC8 completion and verification.

## Verification and Test Results

```text
docker compose -p assessment exec backend pytest

37 passed, 12 skipped, 4 warnings in 15.06s
```

## Architectural Decisions & Divergences
- BC8 does not gate retrieval; it only produces the bounded confidence signal BC9 will consume.
- Deterministic tests inject fake rerankers so the backend suite does not depend on downloading model weights.
- The local reranker is loaded lazily once per process rather than eagerly at FastAPI startup; this preserves the "not per request" requirement while keeping tests lightweight.

## BC9 Handover
- Gate on `reranked.top_relevance_score`, never `hybrid_results.top_score`.
- Add query expansion only for low-confidence retrieval.
- Keep `fetch_page_image` internal-only unless a future source-page viewing feature defines authorization explicitly.
