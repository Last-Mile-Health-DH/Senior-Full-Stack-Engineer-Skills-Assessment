# Pull Request: BC13 - Documents Upload Page and Upload Limits Config

## Executive Summary
BC13 adds the Next.js `/documents` route and a backend upload-limits endpoint so client-side validation reads backend-owned limits. The UI supports upload progress, processing polling, failed/indexed statuses, optimistic delete, rollback on delete failure, and a staged auth-header helper.

## Changes Introduced

### Backend
- Added `GET /api/v1/config/upload-limits`.

### Frontend
- Added `frontend/src/app/documents/page.tsx`.
- Added shared upload/API helpers in `frontend/src/lib/documentsCore.js`.
- Added deterministic frontend tests using Node's built-in test runner.
- Added `frontend/.env.local.example` with `NEXT_PUBLIC_API_BASE_URL`.

### Verification
- Pending rebuilt-image targeted backend run: `docker compose -p assessment exec backend pytest app/tests/test_upload_config.py -vv`.
- Frontend deterministic run passed: `npm test --prefix frontend -- --runInBand` (`1 passed`, `0 failed`).
- Blocker: backend image rebuild failed during pip install with a package hash mismatch (`Expected sha256 edd815...; Got 2ba3...`), so backend container pytest has not run yet.

## Architectural Notes
- Upload limits are not duplicated as frontend constants.
- Frontend validation remains UX-only; backend magic-byte/page-count validation remains authoritative.
