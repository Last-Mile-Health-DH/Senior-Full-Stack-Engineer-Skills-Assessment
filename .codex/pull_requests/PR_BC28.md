# PR BC28 - Corrective Docs Fold-Back

## Summary
- Folded BC21-BC27 decisions and environment variables into architecture and env docs.
- Updated README/tests-README with Docker build strategy, exact numeric grounding, gold-eval workflow, and Playwright status.
- Added `.codex/handover.json` final handover records for implementation and verification.
- Checklist buildrun follow-up rewrote public-facing docs, added `SUBMISSION_CHECKLIST_STATUS.md`, documented AWS/Lambda/Bedrock deployment planning, and made current UI/worker/e2e limitations explicit.
- Follow-on production-gap closure wires Chainlit to `/api/v1/chat`, adds structured citation metadata/rendering, schedules ingestion from uploads, and scaffolds Playwright smoke coverage.

## Verification
- `python3 -m compileall backend/app gold_standard`
- `docker compose -p assessment exec backend pytest`
- `npm test --prefix frontend -- --runInBand`

## Known Remaining Limitations
- Per-sentence multi-source citation placement remains future UI refinement; Chainlit currently renders answer-level notes.
- Real gold score floors remain untrusted until corpus fetch/checksum pinning, indexing, and expected-answer human verification are complete.
- Clean-clone validation and live AWS deployment have not been performed.
