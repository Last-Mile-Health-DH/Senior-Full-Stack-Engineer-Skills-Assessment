# Test Execution & Verification Guide (tests-README FILE)

This document is the canonical reference for executing automated tests on the **Last Mile Health RAG** system. It details the setup, tools, and execution procedures for the backend FastAPI suite, the Next.js deterministic test suite, Chainlit client tests, and the Playwright e2e smoke suite.

---

## 1. Testing Architecture Overview

Automated tests are divided into three isolated, progressive layers:

1. **Backend Deterministic Suite (`pytest`):** Validates routes, schemas, database models, computed columns, Alembic migrations, rate limits, and caching systems. Highly optimized, isolated from network requests, and fully mocked.
2. **Frontend Deterministic Suite (`node --test`):** Validates the Next.js document upload helper layer, public document API calls, upload state machinery, deletions, and polling merge behavior without a browser.
3. **End-to-End (E2E) Integration Suite (`Playwright`):** Simulates public browser flows for uploading a generated table-bearing PDF, waiting for indexing, loading Chainlit, asking a table-dependent question, and verifying both the expected table-derived value and cited page note.

## Current Reviewer Test Status

All results below are from the chat-UI/response-presentation buildrun on branch `codex/chat-ui-requirement-polish`.

| Tier | Status | Command and last result |
|---|---|---|
| Backend deterministic full suite | Verified complete | `docker compose -p assessment exec backend pytest` -> **`224 passed, 12 skipped, 4 warnings`** |
| Backend RAG system integration suite | Verified complete (new) | `docker compose -p assessment exec backend pytest app/tests/test_rag_system_integration.py -vv` -> **`17 passed`** |
| Model router + provider selection | Verified complete (new) | `pytest app/tests/test_model_router.py app/tests/test_generation_provider.py` -> **`12 + 12 passed`**: cheapest-configured-provider routing, placeholder-key rejection, Gemini/OpenAI/Anthropic request shapes, honest degradation |
| Judge provider routing | Verified complete (new) | `pytest app/tests/test_judge_reproducibility.py` -> **`5 passed`**: judge pinned to Anthropic Opus, Gemini/OpenAI fallback clients, deterministic fallback, reasoning-part filtering |
| Dynamic chunking strategy | Verified complete (new) | `pytest app/tests/test_chunk_strategy.py` -> **`9 passed`**: table forces structure-aware, hierarchy vs. flat scan, fixed-size overlap, decision recorded to metadata |
| Embedding reuse / cross-session dedup | Verified complete (new) | `pytest app/tests/test_embedding_reuse.py` -> **`6 passed`**: identical text embedded once across documents/sessions, scoped by embedding model; a re-upload by a **different user in a different chat session** reuses the stored vectors and embeds nothing (source deduplicated in the vector DB, not re-indexed) |
| Cache hit vs. fresh retrieval | Verified complete | `pytest app/tests/test_rag_system_integration.py` (exact/semantic hit + cost): a repeat question is served `exact_hit`/`semantic_hit` from the prompt→response cache with **zero** tokens and cost; a fresh question is a `miss` that retrieves + generates and is costed; a filtered answer is never cached |
| Gold eval — compact multi-type corpus | Verified (local Gemini judge) | `python -m gold_standard.runner --trigger manual` -> **overall 91.12 / 100** over 8 questions spanning table/numeric, semantic-paraphrase, heading-hierarchy, OCR-only, cross-document synthesis, and refusal. `dosing 100 · refusal 100 · semantic 100 · synthesis 88.75`. Judge is the honest Gemini fallback, not the pinned Opus. See `gold_standard/gold_eval_report.md`. |
| Decision-level audit trail | Verified complete (new) | `pytest app/tests/test_audit_trail.py` -> **`3 passed`**: one question replays router + retrieval score from one key; a failed trace write never poisons the caller's transaction |
| Provider rate-limit + network retry | Verified complete (new) | `pytest app/tests/test_gemini_retry.py` -> **`7 passed`**: a transient 429/5xx is retried with backoff and recovers; a transient DNS/connection error (`httpx.TransportError`) is retried and recovers; a persistent 429 or network error eventually raises; a real 400 is never retried; the `Retry-After` header is honored. Guards the free-tier rate-limit and WSL2/Docker DNS blips that stalled corpus ingestion. |
| Dynamic ingestion-agent routing | Verified complete (new) | `pytest app/tests/test_ingestion_routing.py` -> **`7 passed`**: the ingestion planner requires no specific vendor key, routes to the cheapest available provider (`Task.FAST`), falls back to the deterministic local path when no key is configured, rejects placeholder keys, and reconstructs the Gemini 3 model turn (thought signature + call id) so multi-turn planning does not 400. |
| Semantic cache model scoping | Verified complete | `pytest app/tests/test_cache.py` -> vectors never compared across embedding models; a missing model label now fails loudly (migration 0016) |
| Backend response presenter | Verified complete (new) | `docker compose -p assessment exec backend pytest app/tests/test_response_presenter.py -vv` -> **`19 passed`** |
| Frontend deterministic suite | Verified complete | `npm test --prefix frontend` -> **`24 passed`** |
| Chainlit client tests | Verified complete | `python3 -m unittest chainlit_app.tests.test_chat -v` -> **`10 passed`** |
| Playwright chat-UI e2e | Verified complete (new) | `npx playwright test e2e/chat-ui.spec.ts` -> **`16 passed`** in real Chromium, covering both chat surfaces at 375/768/1024/1440 px |
| Playwright upload-to-citation e2e | Scaffolded, not run in this pass | `frontend/e2e/upload-chainlit-citation.spec.ts` needs a live stack with a real ingestion round trip |
| Real gold manual/CI score runs | Not trusted yet | Requires corpus fetch, TOFU checksum pinning, indexing, and human expected-answer verification before score-floor checks mean anything |
| Clean-clone run | Not complete | Must be run from a fresh clone before claiming reviewer-ready reproducibility |

> **Known flaky test:** `test_scheduler_singleton.py::test_only_one_concurrent_singleton_job_executes` occasionally fails when the full suite runs against a database under concurrent load — both pooled sessions momentarily fail to acquire the advisory lock (a safe outcome: no double-run) instead of exactly one winning. It passes in isolation and on an unloaded run. This is a test-timing/connection-pool artifact, not a production defect: the advisory-lock singleton guard was verified with a real two-connection concurrency test. Re-run the single test if the full-suite run trips it.

### What the new suites cover

**`app/tests/test_rag_system_integration.py` (17 tests)** drives the real `/api/v1/chat` path against a real multi-document pgvector corpus — real hybrid search (vector + full-text + RRF), real compaction, the real conversation window, real guardrails, the real presenter, and the real caches. Only the cross-encoder (weights must not download) and hosted embeddings (network) are substituted; generation uses the production `DeterministicGenerationClient`, so the citation contract is exercised for real.

| Concern | Test |
|---|---|
| Corpus synthesis | An answer spanning two documents cites both, numbered in first-appearance order |
| No hallucinated sources | Every cited chunk id is one that retrieval actually returned, and exists in the database |
| Off-corpus question | Returns a concise, uncited no-answer instead of a nearest-neighbour guess |
| Exact cache | Second identical question is `exact_hit`, does not regenerate, and rebuilds the same source list |
| Cache key normalization | Case and punctuation differences still hit the cache |
| Semantic cache | A reworded question is served as `semantic_hit` without regenerating |
| Cache hygiene | A filtered answer is never written to the cache |
| Cost accounting | A generation is costed from model pricing; a cache hit costs zero tokens and zero dollars |
| Prompt injection (document) | A hostile PDF's `</context>`, `System:`, `Assistant:`, and "ignore previous instructions" are neutralized before generation |
| Prompt injection (question) | Asking the model to print its system prompt does not leak it |
| System-prompt leak | An answer echoing the system prefix is filtered by the leak canary |
| Numeric grounding | An unsupported dose (500 ml) is filtered rather than shown |
| Rate limiting | The per-session limit returns 429 and is enforced *before* retrieval, generation, and the cache |
| Compaction | A long document is held inside the token budget while keeping the sentence the question is about |
| Sliding context window | Old turns are summarized away; recent turns are kept verbatim |
| Idempotency | Concurrent duplicate questions generate exactly once |

**`app/tests/test_generation_provider.py`** covers the model-provider boundary without any network call (the Anthropic client is injected as a fake):

| Concern | Why it matters |
|---|---|
| A placeholder key does not select the hosted client | `.env.example` ships `ANTHROPIC_API_KEY=your-anthropic-api-key-here`. If that counted as configured, every chat turn would 401 at answer time instead of falling back cleanly. |
| The request omits `temperature` / `top_p` / `top_k` | These are **removed** on the current models (Sonnet 5, Opus 4.8/4.7) — sending any of them is a 400 that would break every answer. |
| Thinking is explicitly disabled | On Sonnet 5, *omitting* the field runs adaptive thinking, and thinking tokens count against `max_tokens` — with a 500-token answer budget that would truncate the answer mid-sentence. |
| The `cache_control` breakpoint survives to the API | The stable system prefix is what makes repeat turns cheap. |
| Cached prefix tokens are still counted for cost | Dropping the cache-read half would under-report spend. |
| A refusal or a provider outage becomes an honest no-answer | A model outage must never surface as a fabricated answer. |
| An unusable page image is dropped, not fatal | With local storage a page image is a filesystem path, not a URL or base64 blob; sending it is a 400 that would take down the whole answer for a cosmetic attachment. |

**`app/tests/test_response_presenter.py` (19 tests)** covers the presentation boundary: sentence-end superscripts, multi-source markers on one sentence, invalid `[cite:99]` markers dropped with no reference created, leading filename/document-name prefixes stripped, internal details (chunk ids, retrieval modes) removed, repeated caveats collapsed, paragraphs and bullets preserved, reference entries built from chunk metadata only (a model-invented reference list is discarded), concise no-answer with no citations, and a jargon guard on all user-facing copy.

**`frontend/e2e/chat-ui.spec.ts` (16 tests, real Chromium)** covers active navigation state, the hamburger drawer opening/closing/Escape/close-on-navigate at 375/768/1024, the permanent sidebar at 1440, the loading row appearing on submit and being replaced by the answer, duplicate-send prevention, superscripts linked to a `Sources` list, a concise no-answer rendering no empty source list, and the `+` upload button being present with no horizontal overflow and no control overlap on **both** chat surfaces at all four viewports.

**`chainlit_app/tests/test_chat.py` (10 tests)** covers the backend client request shape, the loading placeholder being sent and then replaced in place, reference rendering that mirrors the backend presenter, no empty source list on a refusal, the documented `[[UI.header_links]]` upload button, and a jargon guard on Chainlit copy.

### Continuous integration (`.github/workflows/ci.yml`)

A green local run proves very little about a reviewer's machine: a warm Docker cache hides missing architectures, missing system packages, and models downloaded at runtime — the failures a cold clone hits first. CI exists to close exactly that gap.

| Job | What it proves |
|---|---|
| `frontend` | `npm ci` (so the lockfile is reproducible), `tsc --noEmit`, 21 deterministic tests, and a real `next build` |
| `chainlit` | The 10 client tests pass with **no dependencies installed at all** — if this job ever needs a `pip install`, the test stubbing has leaked |
| `backend` | `docker compose build --no-cache backend`, stack up, health wait (which also proves Alembic applies to an **empty volume**), reranker loads with `HF_HUB_OFFLINE=1` (no runtime model download), full pytest, the integration suite, and an Alembic `downgrade base` → `upgrade head` round trip |
| `e2e` | `docker compose build --no-cache` for the **whole stack**, every service reaches health, then Playwright against both chat surfaces at all four viewports |
| `verified` | An explicit `needs:` gate over all of the above, so nothing downstream can run while any check is red or skipped |

The `--no-cache` builds are the point: they run on a GitHub-hosted runner, which is a machine that is not the author's and has no warm layers.

### Viewport checks performed

Real Chromium, both chat surfaces, screenshots reviewed:

| Viewport | Next.js `:3000` | Chainlit `:8000` |
|---|---|---|
| 375 x 812 | Pass | Pass |
| 768 x 1024 | Pass | Pass |
| 1024 x 768 | Pass | Pass |
| 1440 x 900 | Pass | Pass |

No horizontal scrolling, no clipped controls, no overlapping text, and the composer is never covered. One defect was found this way and fixed: a hand-rolled floating upload button on Chainlit collided with Chainlit's own header link at 1440 px, which no assertion had caught — it was replaced with Chainlit's documented `[[UI.header_links]]` component.

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

*   **Run BC12 chat verification:**
    ```sh
    docker compose -p assessment exec backend pytest app/tests/test_chat.py -vv
    ```

*   **Run BC13 upload config verification:**
    ```sh
    docker compose -p assessment exec backend pytest app/tests/test_upload_config.py -vv
    ```

*   **Run BC14 guardrail verification:**
    ```sh
    docker compose -p assessment exec backend pytest app/tests/test_guardrails.py -vv
    docker compose -p assessment exec backend pytest app/tests/test_chat.py -vv
    docker compose -p assessment exec backend pytest app/tests/test_cache.py -vv
    ```

*   **Run BC15 auth/rate-limit verification:**
    ```sh
    docker compose -p assessment exec backend pytest app/tests/test_auth.py -vv
    docker compose -p assessment exec backend pytest app/tests/test_rate_limit.py -vv
    docker compose -p assessment exec backend pytest app/tests/test_migrations.py -vv
    docker compose -p assessment exec backend pytest app/tests/test_documents.py -vv
    docker compose -p assessment exec backend pytest app/tests/test_chat.py -vv
    ```

*   **Run the response-presentation and citation verification:**
    ```sh
    docker compose -p assessment exec backend pytest app/tests/test_response_presenter.py -vv
    docker compose -p assessment exec backend pytest app/tests/test_chat.py -vv
    ```

*   **Run the full RAG system integration suite (multi-document corpus):**
    ```sh
    docker compose -p assessment exec backend pytest app/tests/test_rag_system_integration.py -vv
    ```
    This exercises corpus synthesis, exact/semantic caching, cost accounting, prompt-injection
    interception, rate limiting, context compaction, the sliding conversation window, and
    idempotency against a real pgvector corpus.

*   **Run BC21-BC28 corrective verification:**
    ```sh
    docker compose -p assessment exec backend pytest app/tests/test_scheduler_singleton.py -vv
    docker compose -p assessment exec backend pytest app/tests/test_cost.py -vv
    docker compose -p assessment exec backend pytest app/tests/test_rate_limit_indexes.py -vv
    docker compose -p assessment exec backend pytest app/tests/test_semantic_cache_model_scope.py -vv
    docker compose -p assessment exec backend pytest app/tests/test_numeric_grounding.py -vv
    docker compose -p assessment exec backend pytest app/tests/test_anomaly_detection.py -vv
    docker compose -p assessment exec backend pytest app/tests/test_judge_reproducibility.py -vv
    docker compose -p assessment exec backend pytest app/tests/test_gold_standard.py -vv
    docker compose -p assessment exec backend pytest -m golden_set -vv
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
- **BC3/BC4 Document Tests:** `backend/app/tests/test_documents.py` verifies upload validation, deduplication, status/list/delete endpoints, visible background enqueueing of the ingestion worker for new uploads, no duplicate enqueue for indexed duplicates, the BC4 `detect_page_structure` contract, OCR fallback wiring, and the upload-to-rasterization worker path that persists `page_images` rows. `backend/app/tests/test_rasterization.py` validates the instrumented worker transition from `processing` to `indexed`, including page image persistence and chunking metadata. Poppler and Tesseract calls are mocked in deterministic tests; the Docker image includes the real binaries for manual or integration runs.
- **BC5 Chunking/Embedding Tests:** `backend/app/tests/test_chunking.py` verifies chunk size limits, configured overlap behavior, heading/table-aware splitting, deterministic embedding generation, embedding dimension validation, pgvector persistence, and database-generated `content_tsv`. Hosted OpenAI/Voyage embedding calls are not made in deterministic tests; tests inject a fake embedding client, while local development without provider keys uses the deterministic fallback path.
- **BC6 Ingestion Agent Tests:** `backend/app/tests/test_ingestion_agent.py` verifies the page-scaled ingestion iteration cap, the static tool scope, agent trace logging, table-page image parity with the deterministic path, per-page fallback metadata, and prompt-injection/tool-scope containment. Hosted Anthropic calls are not made in deterministic tests; tests inject a scripted model client.
- **BC7 Retrieval Tests:** `backend/app/tests/test_retrieval.py` verifies literal Reciprocal Rank Fusion scoring, pgvector vector retrieval, generated-column full-text lexical retrieval, hybrid ordering, vector-only fallback, deleted-document exclusion, query embedding dimension mismatch, and transaction-local `hnsw.ef_search`.
- **BC8 Rerank Tests:** `backend/app/tests/test_rerank.py` verifies empty-input behavior, sigmoid-bounded score ordering, `top_n` limiting, hosted-provider strategy selection, and explicit failure when a hosted provider is configured without an adapter. Deterministic tests inject fake rerankers and do not download local cross-encoder weights.
- **BC9 Retrieval Agent Tests:** `backend/app/tests/test_retrieval_agent.py` verifies high-confidence no-expansion, low-confidence expansion, reranker-score gating instead of raw RRF `top_score`, malformed expansion fallback, merge/dedup best fused score retention, iteration-bound deterministic fallback, no public page-image route, and trace-context propagation. Deterministic tests inject fake `hybrid_search`, `rerank`, `expand_query`, and `fetch_page_image` functions; no hosted LLM or model-weight download occurs.
- **BC10/BC14 Orchestrator Tests:** `backend/app/tests/test_orchestrator.py` verifies lexical-overlap compaction, document-order restoration, zero-overlap fallback, static import-boundary enforcement, multimodal image attachment, text-only degradation, context-block payload assembly, retrieval failure propagation, and removal of the BC10 output-filter stub after BC14. Tests inject fake retrieval-agent instances and do not call retrieval internals directly.
- **BC11 Cache Tests:** `backend/app/tests/test_cache.py` verifies query normalization/hash equivalence, exact-cache retrieval/generation skip behavior, semantic threshold hit/miss behavior, hit-count/last-used updates, exact TTL expiry, semantic LRU eviction, document-deletion invalidation, prompt-cache control toggling, and write-eligibility false skips. Semantic-cache tests inject deterministic embedding clients and never call hosted embedding APIs.
- **BC12 Chat Tests:** `backend/app/tests/test_chat.py` verifies idempotency duplicate handling, concurrent duplicate suppression, conversation-summary threshold behavior, latest-summary-only context loading, exact/semantic cache hits skipping RetrievalAgent and generation, empty-corpus upload-first behavior, retrieval-unavailable responses, audit finalization, source chunk persistence, and structured citation metadata. Tests inject fake generation clients, fake RetrievalAgent instances, fake embedding clients, and no-op Chainlit step wrappers.
- **BC13 Frontend/Upload Config Tests:** `backend/app/tests/test_upload_config.py` verifies the settings-derived upload-limits endpoint. `npm test --prefix frontend` runs deterministic Node tests for the `/documents` page source, frontend fetch/XHR helpers, upload validation, upload progress, mocked polling transitions, failed status rendering support, optimistic delete, rollback, and public/no-auth document calls.
- **BC14 Guardrail Tests:** `backend/app/tests/test_guardrails.py` verifies grounded/fabricated answers, leak canaries, PII provenance, empty-answer filtering, tool-result sanitizer delimiter defense, filtered-response cache blocking, input-validation audit rejection, security headers, and configured CORS. No hosted LLMs, hosted embeddings, hosted auth providers, or reranker downloads are used.
- **BC15 Auth/Rate-Limit Tests:** `backend/app/tests/test_auth.py` and `backend/app/tests/test_rate_limit.py` verify JWT issuance/verification, explicit public document-route access for the local reviewer stack, anonymous-chat flag behavior, per-session limits, per-IP limits via `query_audit_log.client_ip`, `Retry-After`, and rate-limit-before-cache behavior. Rate-limit tests use DB fixtures rather than external counters.
- **BC21-BC28 Corrective Tests:** Scheduler singleton tests verify Postgres advisory-lock execution and lock release. Cost/index/cache tests cover `MODEL_PRICING_JSON`, rate-limit indexes, and semantic-cache `embedding_model` scoping/drift cleanup. Numeric grounding tests enforce exact clinical numeric output matching, including 5 ml pass / 15 ml fail and tolerance ignored for generated answers. Anomaly/Judge/Gold tests cover cadence split, reproducible `JudgeAgent` metadata, SQLAlchemy-backed gold eval persistence, verified-question skipping, and rubric/deviation math. Deterministic tests inject fake chat and fake judge clients and never call hosted LLMs.

### 2.4 Current Cycle Verification Log

Chat-UI and response-presentation buildrun (branch `codex/chat-ui-requirement-polish`):

```text
docker compose -p assessment exec backend pytest
224 passed, 12 skipped, 4 warnings

docker compose -p assessment exec backend pytest app/tests/test_rag_system_integration.py -q
17 passed in 21.50s

npm test --prefix frontend
24 passed

python3 -m unittest chainlit_app.tests.test_chat
10 passed

npx tsc --noEmit --prefix frontend
clean

PLAYWRIGHT_BASE_URL=http://localhost:3000 \
PLAYWRIGHT_CHAINLIT_BASE_URL=http://localhost:8000 \
npx playwright test e2e/chat-ui.spec.ts
16 passed (real Chromium)

curl -s http://localhost:6100/health
{"status":"ok","database":"ok"}

curl -s -o /dev/null -w "%{http_code}" -L http://localhost:3000/   -> 200
curl -s -o /dev/null -w "%{http_code}" -L http://localhost:8000/   -> 200
```

Historical logs from earlier cycles follow.


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

Historical BC12-BC15 image-build issue, now superseded by the BC21-BC28 rebuild:

```text
python3 -m compileall backend/app
passed

npm test --prefix frontend
1..1
# tests 1
# pass 1
# fail 0
# duration_ms 1696.303333

docker compose -p assessment up -d --build backend frontend
previously failed during backend image build on a pip wheel hash/download error.
The current backend image build is repaired by using no pip cache mount and a CPU-only torch wheel before sentence-transformers.
```

BC21-BC28 corrective verification status:

```text
docker compose -p assessment build backend
passed; backend image includes CPU-only torch and gold_standard package

docker compose -p assessment exec backend pytest app/tests/test_scheduler_singleton.py -vv
3 passed in 2.60s

docker compose -p assessment exec backend pytest app/tests/test_cost.py app/tests/test_numeric_grounding.py app/tests/test_anomaly_detection.py app/tests/test_judge_reproducibility.py -vv
15 passed in 0.83s

docker compose -p assessment exec backend pytest app/tests/test_rate_limit_indexes.py -vv
1 passed in 1.17s

docker compose -p assessment exec backend pytest app/tests/test_semantic_cache_model_scope.py -vv
2 passed in 2.54s

docker compose -p assessment exec backend pytest app/tests/test_gold_standard.py -vv
4 passed in 1.55s

docker compose -p assessment exec backend pytest -m golden_set -vv
1 passed, 131 deselected, 1 warning in 1.81s

docker compose -p assessment exec backend pytest
120 passed, 12 skipped, 4 warnings in 41.03s

npm test --prefix frontend
1 passed

docker compose -p assessment exec backend python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:6100/health', timeout=5).read().decode())"
{"status":"ok","database":"ok"}
```

Gold-eval manual/CI floor commands require the corpus PDFs to be fetched, checksum-pinned, indexed, and human-verified first:

```sh
python -m gold_standard.fetch_corpus
python -m gold_standard.verify_expected --search
python -m gold_standard.runner --trigger manual --sample 8
python -m gold_standard.runner --trigger ci --floor 85
```

---

## 3. Frontend Testing (Node Test Runner)

Frontend deterministic tests verify the `/documents` page source and client-side validation/API helper behavior without a browser or hosted services.

### 3.1 Running Frontend Tests
To run deterministic frontend tests:

*   **Using npm commands from the project root:**
    ```sh
    npm test --prefix frontend
    ```

*   **Running directly from the frontend directory:**
    ```sh
    cd frontend
    npm install
    npm test
    ```

---

## 3.5 Chainlit Client Tests

Chainlit client tests use Python's built-in `unittest` runner with a stubbed Chainlit module and fake HTTP client:

```sh
python3 -m unittest chainlit_app.tests.test_chat -v
```

---

## 4. End-to-End Integration Tests (`Playwright`)

Playwright tests execute in a real headless browser environment to ensure backend services, relational databases, Chainlit, and frontend components communicate correctly. The current smoke spec generates its own table-bearing PDF fixture at runtime, so no PDF binary is committed.

### 4.1 Prerequisites
Before running E2E tests, ensure the local Docker containers are running and healthy:
```sh
docker compose -p assessment up -d --build
```

Make sure Playwright browsers are installed locally (or inside your execution host):
```sh
npm --prefix frontend run playwright:install
```

Set `PLAYWRIGHT_BASE_URL` in the shell when running specs against a non-default frontend URL:

```sh
PLAYWRIGHT_BASE_URL=http://localhost:3000 npm --prefix frontend run test:e2e
```

Optional URL overrides:

```sh
PLAYWRIGHT_BASE_URL=http://localhost:3000 \
PLAYWRIGHT_API_BASE_URL=http://localhost:6100/api/v1 \
PLAYWRIGHT_CHAINLIT_BASE_URL=http://localhost:8000 \
npm --prefix frontend run test:e2e
```

### 4.2 Playwright Commands
Use these commands to execute the E2E suite and verify the complete ingestion-to-citation-retrieval pipeline:

*   **Execute all E2E specs:**
    ```sh
    npm --prefix frontend run test:e2e
    ```

*   **Execute Playwright with the interactive UI runner (highly recommended for local debugging):**
    ```sh
    npm --prefix frontend run test:e2e -- --ui
    ```

*   **View test reports:**
    ```sh
    npm --prefix frontend run playwright:report
    ```

---

## 5. Dependency and Build Reliability Notes

- The backend Docker build originally failed on pip cache/hash corruption. The fix is to install requirements without a pip cache mount:

    ```dockerfile
    RUN pip install --no-cache-dir --default-timeout=180 --retries=10 -r /requirements.txt
    ```

- A later empty wheel payload/hash failure occurred in the `sentence-transformers` / torch dependency chain. The backend now pins CPU-only `torch==2.9.1+cpu` via the official PyTorch CPU wheel index before `sentence-transformers`, preserving the local CrossEncoder reranker while avoiding CUDA wheel downloads.
- The backend image is built from the repository root with `.dockerignore` allowing `backend/`, `gold_standard/`, and `pytest.ini` into the image. This is required so scheduled gold evaluation imports work in production-like containers.
- `poppler-utils` and `tesseract-ocr` are required at the container/system layer for PDF rasterization and OCR. They are mocked in deterministic tests but installed in the backend image for manual and integration runs.
- The Chainlit image uses `uv pip install --system --no-cache -r requirements.txt` to avoid very slow pip resolver backtracking in the Chainlit/OpenTelemetry dependency tree.

---

## 6. Troubleshooting Test Environments

*   **Error: Database Connection Refused / `ConnectionRefusedError`**
    *   *Cause:* The test runner is trying to connect to a Postgres container that is down or uninitialized.
    *   *Fix:* Make sure Postgres is up (`docker compose ps`) or configure the database URL env var (e.g., `DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/assessment_test`) in your test shell.
*   **Error: Missing Poppler/Tesseract binaries on local run**
    *   *Cause:* The ingestion pipeline relies on system utilities for OCR and page rasterization.
    *   *Fix:* Run tests inside the Docker container (`docker compose exec backend pytest`) or install poppler/tesseract locally:
        *   *Ubuntu/Debian:* `sudo apt-get install poppler-utils tesseract-ocr`
        *   *macOS (Homebrew):* `brew install poppler tesseract`
*   **Error: Playwright browsers missing**
    *   *Fix:* Execute `npm --prefix frontend run playwright:install` within the target environment before initiating E2E runs.
