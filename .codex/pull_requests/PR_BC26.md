# PR BC26 - Gold Eval Runner and Persistence

## Summary
- Added SQLAlchemy-native gold eval runner and `/chat` client adapter.
- Persisted `gold_eval_run` and `gold_eval_result` with scores, category breakdowns, judge metadata, lineage, corpus/rubric version, and git SHA when available.
- Bounded production gold-run concurrency without sharing async DB sessions across concurrent lineage reads.

## Verification
- `docker compose -p assessment exec backend pytest app/tests/test_gold_standard.py -vv`
- Full backend suite: `120 passed, 12 skipped`.
