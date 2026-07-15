# PR BC21 - Scheduler Singleton Guard

## Summary
- Added Postgres advisory-lock singleton execution for scheduled job families.
- Added per-job lock offsets for cache hygiene, grading, anomaly detection, config drift, and gold eval.
- Hardened lock release after job exceptions and DB transaction errors.

## Verification
- `docker compose -p assessment exec backend pytest app/tests/test_scheduler_singleton.py -vv`
- Full backend suite: `120 passed, 12 skipped`.
