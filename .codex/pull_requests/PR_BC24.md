# PR BC24 - Anomaly Cadence, Judge Reproducibility, Step Shim

## Summary
- Split anomaly cadence between hourly request metrics and nightly grade/gold metrics.
- Persisted judge model, temperature, and rubric version for response grades and gold eval runs.
- Replaced direct Chainlit-step assumptions with a context-guarded no-op shim.
- Made full-text config explicit and kept idempotency duplicate polling pool-safe.

## Verification
- `docker compose -p assessment exec backend pytest app/tests/test_anomaly_detection.py -vv`
- `docker compose -p assessment exec backend pytest app/tests/test_judge_reproducibility.py -vv`
- Full backend suite: `120 passed, 12 skipped`.
