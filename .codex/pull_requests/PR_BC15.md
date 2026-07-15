# Pull Request: BC15 - JWT Auth and Rate Limiting

## Executive Summary
BC15 adds lightweight JWT session issuance, protects document-management endpoints, keeps chat anonymous when configured, and enforces Postgres-backed per-session/per-IP chat rate limiting before cache lookup. It also adds the additive `query_audit_log.client_ip` migration.

## Changes Introduced

### Backend
- Added `POST /api/v1/auth/session`.
- Added HS256 JWT issue/verify helpers and `require_auth`.
- Protected upload/list/get/delete document routes.
- Added `query_audit_log.client_ip` migration and model field.
- Added per-session and per-IP rate-limit checks with `Retry-After`.

### Verification
- Local compile check passed: `python3 -m compileall backend/app`.
- Pending rebuilt-image targeted runs:
  - `docker compose -p assessment exec backend pytest app/tests/test_auth.py -vv`
  - `docker compose -p assessment exec backend pytest app/tests/test_rate_limit.py -vv`
  - `docker compose -p assessment exec backend pytest app/tests/test_migrations.py -vv`
  - `docker compose -p assessment exec backend pytest app/tests/test_documents.py -vv`
  - `docker compose -p assessment exec backend pytest app/tests/test_chat.py -vv`
- Blocker: backend image rebuild failed during pip install with a package hash mismatch (`Expected sha256 edd815...; Got 2ba3...`), so container pytest has not run yet.

## Architectural Notes
- Chat remains open when `ANONYMOUS_CHAT_ALLOWED=true`.
- Rate limiting runs after idempotency claim but before cache lookup, so cache hits cannot bypass limits.
