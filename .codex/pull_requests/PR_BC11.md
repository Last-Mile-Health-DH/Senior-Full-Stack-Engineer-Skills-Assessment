# Pull Request: [BC11] - Exact and Semantic Cache

## Executive Summary
BC11 implements cache-before-corpus behavior through exact and semantic caches backed by Postgres. It adds prompt-cache control integration and a lightweight in-process cache hygiene scheduler for TTL expiry, semantic LRU eviction, and stale document-reference invalidation.

## Changes Introduced

### Backend
- Added `backend/app/cache/` modules for exact cache, semantic cache, cache service orchestration, and cache hygiene.
- Added `backend/app/scheduling/cache_scheduler.py` and FastAPI lifespan startup/shutdown wiring.
- Added BC11 settings for cache TTL, semantic threshold, prompt caching, scheduler gating, and semantic row cap.

### Cache Behavior
- Normalized exact-cache queries by lowercasing, whitespace collapse, trimming, and trailing punctuation stripping.
- Hashed normalized exact-cache keys with SHA-256.
- Implemented semantic cache lookup using the existing embedding client and dimension guard.
- Updated semantic hits with `hit_count` and `last_used_at`.
- Added `eligible: bool` gates to exact and semantic writes with BC14 TODO comments.
- Added prompt-cache `cache_control: {"type": "ephemeral"}` on the stable system prefix when enabled.

### Documentation
- Added `SEMANTIC_CACHE_MAX_ROWS=5000` to `.env.example`.
- Updated `tests-README.md` and `plan.md` with BC11 verification.
- Logged scheduler, eligibility, and invalidation decisions in `ARCHITECTURE (4).md` section 18.

## Verification and Test Results

```text
docker compose -p assessment exec backend pytest app/tests/test_cache.py -vv

9 passed in 7.74s

docker compose -p assessment exec backend pytest

64 passed, 12 skipped, 4 warnings in 20.89s
```

## Architectural Decisions & Divergences
- Aligned with `ARCHITECTURE (4).md` section 9.
- Scheduler infrastructure starts at BC11 because cache hygiene is required now; BC20 extends the same scheduler.
- Cache invalidation deletes rows referencing missing document IDs, matching the current delete/reupload document lifecycle.

## Handover Log
- Backend implementation completed for BC11.
- Test Agent verified exact hits, semantic hit/miss thresholds, hit metadata updates, TTL expiry, LRU eviction, document deletion invalidation, prompt-cache toggling, and write eligibility.
