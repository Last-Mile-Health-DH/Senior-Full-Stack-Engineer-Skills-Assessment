# Test Execution & Verification Guide (tests-README FILE)

This document is the canonical reference for executing automated tests on the **Last Mile Health RAG** system. It details the setup, tools, and execution procedures for both the backend (FastAPI) and frontend (Next.js & Playwright) testing suites.

---

## 1. Testing Architecture Overview

Automated tests are divided into three isolated, progressive layers to guarantee speed, completeness, and reliability:

1. **Backend Deterministic Suite (`pytest`):** Validates routes, schemas, database models, computed columns, Alembic migrations, rate limits, and caching systems. Highly optimized, isolated from network requests, and fully mocked.
2. **Frontend Component Suite (`Jest` & `React Testing Library`):** Validates the Next.js documents dashboard, upload state machinery, deletions, and layout edge cases.
3. **End-to-End (E2E) Integration Suite (`Playwright`):** Simulates genuine user flows (logging in, uploading a document, waiting for status transitions, loading the Chainlit UI, asking a query, and verifying citations and page images).

---

## 2. Backend Testing (`pytest`)

Backend testing is conducted using `pytest` and `asyncio` to handle asynchronous FastAPI routes and database drivers.

### 2.1 Running Tests Inside Docker (Recommended)
Docker containers are pre-packaged with all required libraries (`poppler-utils`, `tesseract-ocr`). To run tests inside the containerized environment:

*   **Run all deterministic checks:**
    ```sh
    docker compose -p assessment exec backend pytest
    ```

*   **Run with a coverage report:**
    ```sh
    docker compose -p assessment exec backend pytest --cov=app --cov-report=term-missing
    ```

*   **Run a specific test file or directory:**
    ```sh
    docker compose -p assessment exec backend pytest app/tests/test_schema_constraints.py
    ```

*   **Run BC4 rasterization worker verification:**
    ```sh
    docker compose -p assessment exec backend pytest app/tests/test_rasterization.py -vv -s
    ```

*   **Run BC5 chunking and embedding verification:**
    ```sh
    docker compose -p assessment exec backend pytest app/tests/test_chunking.py -vv -s
    ```

*   **Run BC6 bounded ingestion-agent verification:**
    ```sh
    docker compose -p assessment exec backend pytest app/tests/test_ingestion_agent.py -vv -s
    ```

*   **Run BC7 retrieval verification:**
    ```sh
    docker compose -p assessment exec backend pytest app/tests/test_retrieval.py -vv -s
    ```

*   **Run BC8 reranking verification:**
    ```sh
    docker compose -p assessment exec backend pytest app/tests/test_rerank.py -vv -s
    ```

*   **Run BC9 retrieval-agent cascade verification:**
    ```sh
    docker compose -p assessment exec backend pytest app/tests/test_retrieval_agent.py -vv
    ```

*   **Run BC10 orchestrator/generation-assembly verification:**
    ```sh
    docker compose -p assessment exec backend pytest app/tests/test_orchestrator.py -vv
    ```

*   **Run BC11 exact/semantic-cache verification:**
    ```sh
    docker compose -p assessment exec backend pytest app/tests/test_cache.py -vv
    ```

### 2.2 Running Tests Locally (Without Docker)
If you are developing locally with a Python virtual environment:

1.  **Activate your virtualenv & Install dependencies:**
    ```sh
    cd backend
    python -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```
2.  **Execute Pytest:**
    ```sh
    pytest
    ```

### 2.3 Mocking & Environmental Variables
Deterministic tests do not make active calls to external LLMs or vector database providers.
- **LLM/API Mocking:** Pytest fixtures intercept and mock Anthropic (`anthropic`), OpenAI (`openai`), and OpenRouter (`openrouter`) endpoints.
- **Database Isolation:** All tests run inside a PostgreSQL transaction that automatically rolls back when the test terminates, preventing database pollution.
- **BC2 Migration Tests:** `backend/app/tests/test_migrations.py` runs `alembic upgrade head` and `alembic downgrade base` against the containerized Postgres database. `backend/app/tests/test_schema_constraints.py` rebuilds the migration head for constraint checks, then validates generated `content_tsv`, `documents.content_hash` uniqueness, `page_images` uniqueness, `query_audit_log.idempotency_key` uniqueness, `agentops_summary`, and document cascade deletion behavior.
- **BC3/BC4 Document Tests:** `backend/app/tests/test_documents.py` verifies upload validation, deduplication, status/list/delete endpoints, the BC4 `detect_page_structure` contract, OCR fallback wiring, and the upload-to-rasterization worker path that persists `page_images` rows. `backend/app/tests/test_rasterization.py` validates the instrumented worker transition from `processing` to `indexed`, including page image persistence and chunking metadata. Poppler and Tesseract calls are mocked in deterministic tests; the Docker image includes the real binaries for manual or integration runs.
- **BC5 Chunking/Embedding Tests:** `backend/app/tests/test_chunking.py` verifies chunk size limits, configured overlap behavior, heading/table-aware splitting, deterministic embedding generation, embedding dimension validation, pgvector persistence, and database-generated `content_tsv`. Hosted OpenAI/Voyage embedding calls are not made in deterministic tests; tests inject a fake embedding client, while local development without provider keys uses the deterministic fallback path.
- **BC6 Ingestion Agent Tests:** `backend/app/tests/test_ingestion_agent.py` verifies the page-scaled ingestion iteration cap, the static tool scope, agent trace logging, table-page image parity with the deterministic path, per-page fallback metadata, and prompt-injection/tool-scope containment. Hosted Anthropic calls are not made in deterministic tests; tests inject a scripted model client.
- **BC7 Retrieval Tests:** `backend/app/tests/test_retrieval.py` verifies literal Reciprocal Rank Fusion scoring, pgvector vector retrieval, generated-column full-text lexical retrieval, hybrid ordering, vector-only fallback, deleted-document exclusion, query embedding dimension mismatch, and transaction-local `hnsw.ef_search`.
- **BC8 Rerank Tests:** `backend/app/tests/test_rerank.py` verifies empty-input behavior, sigmoid-bounded score ordering, `top_n` limiting, hosted-provider strategy selection, and explicit failure when a hosted provider is configured without an adapter. Deterministic tests inject fake rerankers and do not download local cross-encoder weights.
- **BC9 Retrieval Agent Tests:** `backend/app/tests/test_retrieval_agent.py` verifies high-confidence no-expansion, low-confidence expansion, reranker-score gating instead of raw RRF `top_score`, malformed expansion fallback, merge/dedup best fused score retention, iteration-bound deterministic fallback, no public page-image route, and trace-context propagation. Deterministic tests inject fake `hybrid_search`, `rerank`, `expand_query`, and `fetch_page_image` functions; no hosted LLM or model-weight download occurs.
- **BC10 Orchestrator Tests:** `backend/app/tests/test_orchestrator.py` verifies lexical-overlap compaction, document-order restoration, zero-overlap fallback, static import-boundary enforcement, multimodal image attachment, text-only degradation, context-block payload assembly, retrieval failure propagation, and the explicit BC14 output-filter stub. Tests inject fake retrieval-agent instances and do not call retrieval internals directly.
- **BC11 Cache Tests:** `backend/app/tests/test_cache.py` verifies query normalization/hash equivalence, exact-cache retrieval/generation skip behavior, semantic threshold hit/miss behavior, hit-count/last-used updates, exact TTL expiry, semantic LRU eviction, document-deletion invalidation, prompt-cache control toggling, and write-eligibility false skips. Semantic-cache tests inject deterministic embedding clients and never call hosted embedding APIs.

### 2.4 Current Cycle Verification Log

Latest BC9-BC11 targeted and full backend verification:

```text
docker compose -p assessment exec backend pytest app/tests/test_retrieval_agent.py -vv
8 passed in 8.35s

docker compose -p assessment exec backend pytest app/tests/test_orchestrator.py -vv
9 passed in 0.82s

docker compose -p assessment exec backend pytest app/tests/test_cache.py -vv
9 passed in 7.74s

docker compose -p assessment exec backend pytest
64 passed, 12 skipped, 4 warnings in 20.89s
```

---

## 3. Frontend Testing (`Jest` & RTL)

Frontend component tests verify the UI layouts, client-side validation logic, and file management dashboard.

### 3.1 Running Jest Tests
To run unit and integration tests for React components:

*   **Using npm commands from the project root:**
    ```sh
    npm run test --prefix frontend
    ```

*   **Running directly from the frontend directory:**
    ```sh
    cd frontend
    npm install
    npm run test
    ```

*   **Running Jest in watch mode:**
    ```sh
    npm run test:watch --prefix frontend
    ```

---

## 4. End-to-End Integration Tests (`Playwright`)

Playwright tests execute in a real headless browser environment to ensure backend services, relational databases, and frontend components communicate perfectly.

### 4.1 Prerequisites
Before running E2E tests, ensure the local Docker containers are running and healthy:
```sh
docker compose -p assessment up -d --build
```

Make sure Playwright browsers are installed locally (or inside your execution host):
```sh
npx playwright install --prefix frontend
```

### 4.2 Running Playwright Tests
To execute the E2E suite and verify the complete ingestion-to-citation-retrieval pipeline:

*   **Execute all E2E specs:**
    ```sh
    npx playwright test --prefix frontend
    ```

*   **Execute Playwright with the interactive UI runner (highly recommended for local debugging):**
    ```sh
    npx playwright test --ui --prefix frontend
    ```

*   **View test reports:**
    ```sh
    npx playwright show-report --prefix frontend
    ```

---

## 5. Troubleshooting Test Environments

*   **Error: Database Connection Refused / `ConnectionRefusedError`**
    *   *Cause:* The test runner is trying to connect to a Postgres container that is down or uninitialized.
    *   *Fix:* Make sure Postgres is up (`docker compose ps`) or configure the database URL env var (e.g., `DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/assessment_test`) in your test shell.
*   **Error: Missing Poppler/Tesseract binaries on local run**
    *   *Cause:* The ingestion pipeline relies on system utilities for OCR and page rasterization.
    *   *Fix:* Run tests inside the Docker container (`docker compose exec backend pytest`) or install poppler/tesseract locally:
        *   *Ubuntu/Debian:* `sudo apt-get install poppler-utils tesseract-ocr`
        *   *macOS (Homebrew):* `brew install poppler tesseract`
*   **Error: Playwright browsers missing**
    *   *Fix:* Execute `npx playwright install` within the target environment before initiating E2E runs.
