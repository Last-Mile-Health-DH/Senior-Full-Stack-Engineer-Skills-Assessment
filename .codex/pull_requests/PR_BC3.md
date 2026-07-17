# Pull Request: [BC3] - PDF Upload Endpoint & Validation Limits

## 🎯 Executive Summary
This Pull Request delivers the complete, high-performance async PDF upload, polling, listing, and cascading deletion endpoints (`POST`, `GET`, `DELETE`) inside the FastAPI backend, concluding **Build Cycle 3 (BC3)**.

All edge validations (size constraints, magic-byte file headers, and lightweight page limit counting) occur dynamically at the API boundary before any database or storage writes. The pipeline incorporates automatic `SHA-256` content hashing and idempotent, short-circuit deduplication for already-processed documents. Verification is covered with a 100% green test suite executing natively inside the pytest-asyncio event loop using `httpx.AsyncClient`.

---

## 🛠️ Changes Introduced

### 🖥️ Backend (FastAPI / Ingestion API)
- **`backend/requirements.txt`**: Added `pdfplumber` (for fast page count checks) and `asyncpg` (for async database connections).
- **`backend/app/database.py`**: Created asynchronous database connection manager utilizing `create_async_engine`, setting up a pool size of 10 and max overflow of 20, exposing the `get_db` async dependency.
- **`backend/app/documents/routes.py`**: Implemented core document controller routes:
  - `POST /api/v1/documents`: File upload gate enforcing size check against `MAX_PDF_SIZE_MB` (413), magic-bytes `%PDF` check (415), and `pdfplumber` page length checks against `MAX_PDF_PAGES` (413). Deduplicates files using `SHA-256` content hashes.
  - `GET /api/v1/documents/{document_id}`: Polling status endpoint.
  - `GET /api/v1/documents`: Listing endpoint for document metadata display.
  - `DELETE /api/v1/documents/{document_id}`: Cascading deletion handler clearing the SQL rows (chunks and images) and removing the physical file from disk storage.
  - Stubbed authorization headers dependencies with detailed documentation pointing to the full JWT implementation in `BC15`.
- **`backend/app/main.py`**: Registered the new `documents` router in the FastAPI application stack.

### 🧪 Testing & Verification (`/backend/app/tests/`)
- **`backend/app/tests/test_documents.py`**: Implemented a unified, loop-aligned asynchronous test suite using `httpx.AsyncClient`:
  - **Unit Validation Tests**: Mocks the database and `pdfplumber` context managers to assert correct `413`/`415`/`422` rejections on oversized files, renamed non-PDF files, page ceilings, and corrupted layouts.
  - **Database Integration Tests**: Uses transaction-isolated `AsyncSession` database rollbacks to verify successful document insert, status polling, listing, idempotent duplicate short-circuiting, and cascading disk/row deletion.

---

## 🧪 Verification and Test Results

### Pytest Execution inside Backend Docker Container:
```
============================================= test session starts ==============================================
platform linux -- Python 3.12.11, pytest-8.1.1, pluggy-1.6.0 -- /usr/local/bin/python3.12
cachedir: .pytest_cache
rootdir: /usr/src/LMH
plugins: anyio-4.13.0, cov-4.1.0, asyncio-0.23.6
asyncio: mode=Mode.STRICT
collected 6 items                                                                                              

app/tests/test_documents.py::test_upload_rejections_file_size_exceeded PASSED                            [ 16%]
app/tests/test_documents.py::test_upload_rejections_invalid_magic_bytes PASSED                           [ 33%]
app/tests/test_documents.py::test_upload_rejections_page_count_exceeded PASSED                           [ 50%]
app/tests/test_documents.py::test_upload_rejections_invalid_pdf_format PASSED                            [ 66%]
app/tests/test_documents.py::test_upload_flow_success_and_cascade_delete PASSED                          [ 83%]
app/tests/test_documents.py::test_upload_flow_deduplication PASSED                                       [100%]

======================================== 6 passed, 4 warnings in 38.70s ========================================
```
*Result: 100% of unit and database integration tests passed.*

---

## 📐 Design Decisions & Divergences
- **Dynamic Limit Evaluation**: Swapped static module-level loading of size and page count variables for dynamic lookup inside the POST route via getter helper functions. This supports live-env scaling and allows unit testing of rejections by simply patching the getters, completely eliminating Pydantic-recursion gotchas on `os.getenv`.
- **Async HTTPX Testing**: Shifted from synchronous `TestClient` to `httpx.AsyncClient` with `ASGITransport` to run request loops natively inside the active pytest asyncio loop, avoiding connection mismatches.

---

## 🤝 Handover Log
- **From Agent:** `backend-engineer`
- **To Agent:** `orchestrator` (for BC3 cycle closure and BC4 planning)
- **Cycle status:** Fully built, verified, and committed.
