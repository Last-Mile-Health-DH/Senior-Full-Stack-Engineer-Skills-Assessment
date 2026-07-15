# Pull Request: BC12 - Chat Endpoint, Idempotency, and Session Persistence

## Executive Summary
BC12 adds `POST /api/v1/chat` with idempotency, cache-before-retrieval behavior, deterministic generation injection, conversation windowing, session/message persistence, and Chainlit-compatible trace steps. The endpoint claims `query_audit_log.idempotency_key` before cache lookup and delegates retrieval only through the existing Orchestrator/RetrievalAgent boundary.

## Changes Introduced

### Backend
- Added `backend/app/api/v1/chat.py` for chat orchestration.
- Added deterministic generation client boundary in `backend/app/generation/client.py`.
- Added conversation window and rolling summary helpers in `backend/app/chat/conversation.py`.
- Added no-op-safe Chainlit step wrapper in `backend/app/chainlit_steps.py`.
- Persisted user/assistant messages, source chunk IDs, audit metadata, latency, token counts, and deterministic cost placeholder.

### Verification
- Local compile check passed: `python3 -m compileall backend/app`.
- Pending rebuilt-image targeted run: `docker compose -p assessment exec backend pytest app/tests/test_chat.py -vv`.
- Blocker: backend image rebuild failed during pip install with a package hash mismatch (`Expected sha256 edd815...; Got 2ba3...`), so container pytest has not run yet.

## Architectural Notes
- Idempotency runs before cache lookup.
- Exact/semantic cache hits skip RetrievalAgent and generation.
- Retrieval failure returns an honest retrieval-unavailable response and does not generate.
