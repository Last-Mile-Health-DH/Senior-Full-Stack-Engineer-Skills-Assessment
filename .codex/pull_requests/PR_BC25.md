# PR BC25 - Gold Corpus, Questions, Rubric

## Summary
- Integrated `gold_standard/` corpus manifest, question bank, weighted rubric, checksum fetcher, and expected-answer verifier.
- Added ignore rules so downloaded PDFs and generated reports are not committed.
- Preserved rubric weights: numeric accuracy 0.45, grounding 0.25, completeness 0.20, safety/refusal 0.10.

## Verification
- `docker compose -p assessment exec backend pytest app/tests/test_gold_standard.py -vv`
- Corpus fetch/checksum pinning remains a manual prerequisite before trusting real gold scores.
