# PR BC23 - Exact Numeric Grounding

## Summary
- Added shared deterministic numeric grounding for output filtering, nightly grading, and gold grading.
- Enforced 100% exact matching for generated clinical numerical figures; configured tolerance is ignored for generated output.
- Covered dose, fraction, and bare-integer behavior.

## Verification
- `docker compose -p assessment exec backend pytest app/tests/test_numeric_grounding.py -vv`
- Full backend suite: `120 passed, 12 skipped`.
