# PR BC27 - Gold Reports and Deviation Alerts

## Summary
- Added Markdown gold eval report output.
- Added compatible-baseline deviation detection for overall and per-category scores.
- Wrote gold deviations to `anomaly_flag` and structured logs, with rubric/corpus/judge-compatible baseline reset behavior.

## Verification
- `docker compose -p assessment exec backend pytest app/tests/test_anomaly_detection.py app/tests/test_gold_standard.py -vv`
- Full backend suite: `120 passed, 12 skipped`.
