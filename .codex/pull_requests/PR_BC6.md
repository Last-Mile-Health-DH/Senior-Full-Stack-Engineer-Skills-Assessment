# Pull Request: [BC6] - Bounded Ingestion Agent Loop

## Executive Summary
BC6 replaces the fixed-order structure-assessment controller with a bounded ingestion-agent loop. The agent can only request the three BC4 structure tools (`detect_structure`, `extract_text_ocr_fallback`, and `flag_table_pages`), writes trace rows for tool calls, preserves successful per-page assessments, and falls back only for pages that were not completed when an error or iteration cap occurs.

## Changes Introduced

### Backend / Agent Runtime
- Added `backend/app/agents/ingestion_agent.py` with:
  - provider-neutral `ToolUse` blocks;
  - `PageAssessment` handoff models;
  - static ingestion tool schemas;
  - page-scaled iteration cap calculation;
  - Anthropic Messages API client wiring for real runs;
  - per-page fallback behavior for incomplete or failed assessments.
- Added `backend/app/agents/tracing.py` to persist compact tool-call records into `agent_trace_log`.
- Added `backend/app/settings.py` for agent model, trace logging, Anthropic key, and hard ceiling configuration.

### Worker / Chunking Integration
- Updated `backend/app/worker.py` to invoke `IngestionAgent` before chunk preparation.
- Persisted structure metadata and ingestion fallback metadata on `documents.metadata`.
- Passed BC6 page assessments into `prepare_and_persist_document_chunks`.
- Updated `backend/app/documents/chunking.py` to build structured chunking blocks from in-memory page assessments.

### Test Reliability
- Updated `backend/app/database.py` to use `NullPool` when `ASSESSMENT_TESTING=1`, avoiding asyncpg pooled-connection reuse across pytest event loops.
- Added `backend/app/tests/conftest.py` to set `ASSESSMENT_TESTING=1` for deterministic backend tests.

### Documentation
- Updated `plan.md` to mark BC6 complete and add repo-specific BC7/BC8 build plans.
- Updated `tests-README.md` with BC6 commands, mocking notes, and the latest full backend verification result.

## Verification and Test Results

```text
docker compose -p assessment exec backend pytest

24 passed, 12 skipped, 4 warnings in 8.28s
```

## Architectural Decisions & Divergences
- BC6 follows `build-plans-architecture/BUILD_PLAN_BC5-BC20_batch1_BC5-BC10.md` for the bounded ingestion-agent scope.
- The static tool scope is enforced structurally by the tools supplied to the model client, with a runtime guard for unexpected tool names.
- Fallback is intentionally page-scoped: successful earlier pages keep their assessed results, while missing pages are assessed by deterministic fallback.
- BC7/BC8 planning is adapted to the repository's actual SQLAlchemy async-session implementation, even though the architecture prose discusses raw `asyncpg`.

## BC7 Handover
- Implement retrieval under `backend/app/retrieval/`.
- Use SQLAlchemy `text()` queries for pgvector and full-text search.
- Keep RRF scores separate from confidence; RRF is ordering-only.
- Reuse BC5 embedding-client injection patterns for deterministic query embedding tests.

## BC8 Handover
- Add reranking behind one typed `rerank()` entry point.
- Keep deterministic tests independent of model downloads by injecting a fake cross-encoder.
- Produce a bounded `top_relevance_score` for BC9, but do not gate retrieval in BC8.
