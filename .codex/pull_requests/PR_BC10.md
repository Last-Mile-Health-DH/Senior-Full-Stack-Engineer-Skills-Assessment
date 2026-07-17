# Pull Request: [BC10] - Orchestrator Generation Assembly

## Executive Summary
BC10 adds the Orchestrator boundary that delegates retrieval only through `RetrievalAgent.run`. It deterministically compacts retrieved chunks, assembles generation-ready context and image blocks, and keeps the output filter as an explicit BC14 stub.

## Changes Introduced

### Backend
- Added `backend/app/agents/orchestrator.py` with `consult_retrieval_agent`, `assemble_generation_payload`, and `RetrievalUnavailableError`.
- Ensured the Orchestrator imports no `hybrid_search`, `rerank`, SQLAlchemy, or database modules.
- Added prompt-cache control support on the stable system block.

### Retrieval & Generation
- Added `backend/app/retrieval/compaction.py` with lexical-overlap sentence selection, greedy token budgeting, document-order restoration, and first-token fallback.
- Assembled `<context source="..." page="...">...</context>` text blocks and optional image blocks for multimodal models.
- Added the explicit comment: `# STUB: real grounding/leak/PII checks land at BC14`.

## Verification and Test Results

```text
docker compose -p assessment exec backend pytest app/tests/test_orchestrator.py -vv

9 passed in 0.82s
```

## Architectural Decisions & Divergences
- Aligned with `ARCHITECTURE (4).md` sections 7.4 and 15.4.
- `ARCHITECTURE (4).md` section 18 records deterministic context compaction.
- The output filter is intentionally a stub until BC14.

## Handover Log
- Backend/ML implementation completed for BC10.
- Test Agent verified compaction behavior, import boundary, image/no-image paths, context payloads, failure propagation, and the BC14 stub marker.
