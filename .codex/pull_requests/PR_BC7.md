# Pull Request: [BC7] - Retrieval: Vector, Lexical, and Hybrid Fusion

## Executive Summary
BC7 adds the retrieval layer that turns indexed `chunks` rows into ranked candidates for reranking and the future chat pipeline. It supports pgvector search, Postgres full-text search, Reciprocal Rank Fusion, vector-only fallback, and transaction-local HNSW tuning while preserving the repository's SQLAlchemy async-session pattern.

## Changes Introduced

### Retrieval Runtime
- Added `backend/app/retrieval/` with typed `RetrievalCandidate` and `HybridSearchResult` contracts.
- Implemented `vector_search` with query embedding reuse, dimension validation, pgvector cosine distance, indexed-document filtering, optional document filtering, and `SET LOCAL hnsw.ef_search`.
- Implemented `lexical_search` against generated `chunks.content_tsv` with `plainto_tsquery` and `ts_rank_cd`.
- Implemented `reciprocal_rank_fusion` with `RRF_K=60`.
- Implemented `hybrid_search` with vector/lexical merge, deterministic tie-breaking, top-k output, and vector-only mode.

### Configuration
- Added retrieval settings for `RETRIEVAL_TOP_K`, `HYBRID_SEARCH_ENABLED`, `RRF_K`, and `HNSW_EF_SEARCH`.

### Tests
- Added `backend/app/tests/test_retrieval.py` covering exact RRF scores, vector retrieval, lexical rare-term retrieval, hybrid ordering, vector-only mode, deleted-document exclusion, query embedding dimension mismatch, and transaction-local HNSW behavior.

### Documentation
- Updated `plan.md`, `tests-README.md`, and the BC5-BC10 batch plan with BC7 completion and verification.
- Logged the SQLAlchemy async-session implementation divergence from the older raw-`asyncpg` architecture prose.

## Verification and Test Results

```text
docker compose -p assessment exec backend pytest

37 passed, 12 skipped, 4 warnings in 15.06s
```

## Architectural Decisions & Divergences
- RRF scores are ordering-only and must not be treated as confidence; BC8 owns bounded confidence through reranking.
- Retrieval keeps explicit SQL for pgvector/full-text operations, but runs it through SQLAlchemy `AsyncSession` to stay consistent with the implemented backend.
- `chunks.content_tsv` remains database-generated; BC7 reads it but never writes or recalculates it in application code.

## BC8 Handover
- Feed `hybrid_search(...).candidates` into `rerank`.
- Keep RRF `top_score` separate from reranker `top_relevance_score`.
- Inject fake rerankers in deterministic tests to avoid local model downloads.
