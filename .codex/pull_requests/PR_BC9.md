# Pull Request: [BC9] - Retrieval Agent Cascade

## Executive Summary
BC9 adds the Retrieval Agent boundary around BC7 hybrid search and BC8 reranking. The cascade returns immediately on high reranker confidence, expands only low-confidence queries, and keeps page-image access as an internal-only tool for final reranked chunks.

## Changes Introduced

### Backend
- Added `backend/app/agents/retrieval_agent.py` with `RetrievalAgent.run` and `run_retrieval_cascade`.
- Added typed retrieval-agent result models for query expansion, page images, and final agent output.
- Forwarded trace context through supported retrieval tools.

### ML & Retrieval
- Added `backend/app/retrieval/expand_query.py` with strict JSON/Pydantic parsing and safe fallback to `[original_query]`.
- Added `backend/app/retrieval/fetch_page_image.py` for internal-only page image lookup.
- Merged expanded retrieval candidates by `chunk_id`, preserving best fused score before reranking.
- Preserved RRF scores as ordering-only and gated expansion only on `reranked.top_relevance_score`.

## Verification and Test Results

```text
docker compose -p assessment exec backend pytest app/tests/test_retrieval_agent.py -vv

8 passed in 8.35s
```

## Architectural Decisions & Divergences
- Aligned with `ARCHITECTURE (4).md` sections 7.2, 7.3, and 15.3.
- `fetch_page_image` remains internal-only; no public page-image route was added.
- `ARCHITECTURE (4).md` section 18 records the internal-only page-image decision.

## Handover Log
- Backend/ML implementation completed for BC9.
- Test Agent verified high-confidence, low-confidence, malformed expansion, merge/dedup, iteration fallback, route-table, and trace-context cases.
