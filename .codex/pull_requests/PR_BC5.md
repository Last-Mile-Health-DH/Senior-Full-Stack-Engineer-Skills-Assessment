# Pull Request: [BC5] - Chunking & Embeddings

## Executive Summary
BC5 adds the deterministic ingestion tail for structure-aware chunking and embedding persistence. The pipeline honors `CHUNK_SIZE_TOKENS`, `CHUNK_OVERLAP_RATIO`, and `EMBEDDING_MODEL`, preserves tables as atomic chunks, injects section context from headings, validates embedding dimensions, and writes pgvector embeddings into `chunks` while Postgres automatically generates `content_tsv`.

## Changes Introduced

### Backend / Database
- Added `backend/app/documents/chunking.py`.
- Persisted chunk rows with `document_id`, `chunk_index`, `content`, `content_hash`, `section_path`, `page_number`, `token_count`, `embedding`, and `embedding_model`.
- Used `CAST(:embedding AS vector)` for pgvector insertion without writing the generated `content_tsv` column from application code.
- Integrated chunking and embedding into `process_document` before final `status=indexed`.

### ML & Retrieval
- Implemented token-aware chunking with configurable overlap.
- Preserved table blocks as single chunks and preferred heading/section boundaries.
- Prepended the nearest section heading to chunk text before embedding.
- Added OpenAI and Voyage embedding HTTP clients selected by `EMBEDDING_MODEL`.
- Added a deterministic local/test embedding fallback when provider keys are absent.
- Added explicit embedding count and dimension validation against `EMBEDDING_DIM`.

### Tests
- Added `backend/app/tests/test_chunking.py` for chunk size limits, overlap behavior, structure-aware splitting, deterministic embeddings, dimension mismatch rejection, and database persistence.
- Updated `tests-README.md` with BC4/BC5 commands and mocking notes.

## Verification and Test Results

```text
docker compose -p assessment exec backend pytest app/tests/test_chunking.py -vv -s

collected 6 items
app/tests/test_chunking.py::test_chunk_size_limits_respect_configured_token_budget PASSED
app/tests/test_chunking.py::test_chunk_overlap_reuses_tail_tokens PASSED
app/tests/test_chunking.py::test_structure_aware_chunking_preserves_table_boundaries PASSED
app/tests/test_chunking.py::test_deterministic_embedding_generation_is_stable PASSED
app/tests/test_chunking.py::test_embedding_dimension_validation_rejects_mismatches PASSED
app/tests/test_chunking.py::test_chunk_embedding_persistence_populates_vector_and_tsv PASSED

============================== 6 passed in 2.81s ===============================
```

```text
docker compose -p assessment exec backend pytest

collected 32 items
20 passed, 12 skipped, 4 warnings in 10.25s
```

## Architectural Decisions & Divergences
- Implementation follows `ARCHITECTURE (4).md` §4.4 and §6.
- The deterministic local embedding fallback is a test/local reliability fallback; hosted OpenAI/Voyage clients remain the provider-backed path when real keys are configured.
- No architecture divergence was introduced.

## Handover Log
- BC5 Backend/ML implementation completed.
- BC5 Test Agent verification completed with targeted and full-suite containerized pytest commands.
- BC5 is marked complete in `plan.md`, and BC6 retrieval work is planned there.
