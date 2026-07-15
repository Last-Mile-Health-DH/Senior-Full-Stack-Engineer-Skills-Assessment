# Pull Request: BC14 - Guardrails and Output Filtering

## Executive Summary
BC14 replaces the BC10 output-filter stub with deterministic guardrails: input validation, tool-result sanitization, real output filtering, cache eligibility wiring, CORS restriction, and security headers. Filtered answers return a fixed safe fallback and are not written to exact or semantic cache.

## Changes Introduced

### Backend
- Added `backend/app/security/guardrails.py`.
- Sanitized retrieved chunk text and query-expansion reason text at tool-result boundaries.
- Removed the Orchestrator output-filter stub.
- Wired chat cache writes with `eligible = output_filter_status == "passed"`.
- Added app-level request body validation and global security headers.

### Verification
- Local compile check passed: `python3 -m compileall backend/app`.
- Pending rebuilt-image targeted runs:
  - `docker compose -p assessment exec backend pytest app/tests/test_guardrails.py -vv`
  - `docker compose -p assessment exec backend pytest app/tests/test_chat.py -vv`
  - `docker compose -p assessment exec backend pytest app/tests/test_cache.py -vv`
- Blocker: backend image rebuild failed during pip install with a package hash mismatch (`Expected sha256 edd815...; Got 2ba3...`), so container pytest has not run yet.

## Architectural Notes
- Grounding uses deterministic lexical overlap against cited chunks.
- Tool-result sanitizer neutralizes context delimiter breakout and role/instruction markers without corrupting structural tool output.
