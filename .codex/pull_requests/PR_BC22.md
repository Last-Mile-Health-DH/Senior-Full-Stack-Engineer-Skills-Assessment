# PR BC22 - Cost, Rate-Limit Indexes, Semantic Cache Scope

## Summary
- Added `MODEL_PRICING_JSON` cost computation with explicit unpriced-model warnings.
- Added rate-limit composite indexes for session/IP hot-path counts.
- Scoped semantic-cache rows by `embedding_model` and added drift cleanup.

## Verification
- `docker compose -p assessment exec backend pytest app/tests/test_cost.py -vv`
- `docker compose -p assessment exec backend pytest app/tests/test_rate_limit_indexes.py -vv`
- `docker compose -p assessment exec backend pytest app/tests/test_semantic_cache_model_scope.py -vv`
