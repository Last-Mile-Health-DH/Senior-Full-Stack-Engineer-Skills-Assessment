# Pull Request: [BC4] - Structure Detection & Page Rasterization

## Executive Summary
BC4 completes the ingestion worker path that moves uploaded PDFs from `processing` to `indexed`. The worker now emits granular stage logs, reads PDFs from the same local storage path used by the upload endpoint, strips padded `CHAR(64)` hashes before file lookup, persists structured page images through the current schema, and fails documents explicitly instead of silently leaving them in progress.

## Changes Introduced

### Backend
- Replaced the stale `app.worker.process_document` implementation with an instrumented worker orchestrator.
- Logged document lookup, status checks, upload path resolution, file loading, structure detection, rasterization, chunk preparation, commits, rollbacks, and exception handling.
- Fixed the early-exit bug caused by padded `documents.content_hash` values being used directly in PDF filenames.
- Aligned BC4 processing storage with `backend/uploads`, matching the BC3 upload endpoint.
- Ensured failure paths commit `status=failed` plus metadata instead of returning with `status=processing`.

### ML / Ingestion
- Reused the BC4 `pdfplumber` structure detection path for table/figure signals.
- Continued storing rasterized table/figure pages in `page_images.storage_ref`.

### Tests
- Updated `backend/app/tests/test_rasterization.py` to cover the full worker transition from `processing` to `indexed`.
- Mocked PDF parsing, rasterization, and embeddings so the deterministic suite makes no external calls.

## Verification and Test Results

```text
docker compose -p assessment exec backend pytest app/tests/test_rasterization.py -vv -s

collected 1 item
app/tests/test_rasterization.py::test_rasterization_and_struct_detection PASSED

============================== 1 passed in 2.79s ===============================
```

## Architectural Decisions & Divergences
- Implementation follows `ARCHITECTURE (4).md` §4.3 and §15.2.
- No architecture divergence was introduced.

## Handover Log
- BC4 Backend/ML implementation completed.
- BC4 Test Agent verification completed with the targeted containerized pytest command.
- BC4 is marked complete in `plan.md`.
