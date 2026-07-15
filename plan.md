# Development Build Plan (plan.md)

## Current Status: [~] Multi-Provider Routing, Dynamic Chunking, Observability — In Progress

### Active Cycle: Provider routing, chunking, dedup, audit trail, gold eval

**Objective:** make the RAG pipeline use whichever configured API key best fits each
agentic task (cost-optimized), pin the judge to Anthropic Opus, choose chunking strategy
per document, dedup embeddings across sessions, and give every decision an end-to-end audit
trail — then run the gold-standard evaluation against a real corpus.

**Completed and verified (backend suite: 208 passed, 12 skipped):**
- [x] `core/model_router.py`: cheapest configured provider per task; provider derived from
  model name + real keys; `MODEL_ROUTING=auto|manual`.
- [x] Three generation clients (Anthropic, OpenAI, Gemini) + three embedding providers
  behind one protocol each. Gemini embeddings use Matryoshka truncation to 1536 dims to
  fit the fixed-width pgvector column without a migration.
- [x] JudgeAgent pinned to Anthropic Opus; Gemini/OpenAI/deterministic fallbacks each
  logged; run metadata records the actual judge.
- [x] Honest degradation: `/chat` `model_status` + a plain-language notice in both chat
  UIs + an `agent_trace_log` row.
- [x] Dynamic chunking (`documents/chunk_strategy.py`): structure-aware when a table or a
  navigable hierarchy exists, fixed-size + 15% overlap otherwise; decision persisted.
- [x] Embedding reuse: identical chunk text embedded once across documents/sessions,
  scoped by `embedding_model`.
- [x] Decision-level audit trail (migration 0015): router choice + reason, retrieval mode +
  reranker score, chunking strategy, all under one `query_audit_log_id`.
- [x] Bugs found by real ingestion: Gemini `batchEmbedContents` 100-item cap; Gemini 3
  `thought` parts leaking into answers/scores; a best-effort trace write poisoning the
  caller's transaction on a deadlock (fixed with a SAVEPOINT); `semantic_cache` model
  default masking cross-model comparison (migration 0016).
- [x] Scheduler singleton verified: five jobs, distinct advisory-lock ids, `gold_eval` on
  `0 3 * * *`; lock released on crash.

**Pending:**
- [ ] Gold-standard eval run against the indexed corpus (Gemini generation + judge locally;
  Opus judge in production). Score is honest-labeled by the judge that produced it.
- [ ] End-to-end proofs against the real corpus (per-doc strategy, embedding reuse,
  audit-chain replay, semantic search with no lexical overlap, degraded-mode notice).
- [ ] Clean-clone run.

---

## Prior Cycle: Chat UI Requirement & Response Presentation — Complete
**Active Build Cycle:** Chat UI Requirement Audit and Response Presentation (branch `codex/chat-ui-requirement-polish`)

---

## Active Cycle: Chat UI Requirement & Response Presentation

**Status:** [x] Implemented and verified. Playwright now runs in a real browser; clean-clone run and real gold scoring remain pending.

### Objective
Audit the chat-surface requirement against the starter, then deliver a polished chat experience whose answers are grounded, concise, plainly written, and cited with Chicago-style superscripts at the end of each supported sentence.

### Chat-surface decision
**Both surfaces are supported, alongside each other** — the starter's preferred option. Next.js (`:3000`) and Chainlit (`:8000`) are thin, equivalent clients over the same `/api/v1/chat` contract. Neither owns retrieval, generation, or citation logic, so they cannot disagree; a divergence is a bug. Logged in `ARCHITECTURE (4).md` §18.

### Completed Work
- [x] **RESP1/RESP2** `backend/app/chat/response_presenter.py` — the single boundary owning writing-style and citation rules. Validates `[cite:n]` markers against backend candidates, moves them to the end of the sentence they support, renders Chicago superscripts, drops invalid markers, and builds the reference list from chunk metadata only.
- [x] **RESP3** Generation prompt rewritten with the citation contract and numbered `<context id="n">` blocks. The deterministic client no longer opens answers with `Based on <filename>.pdf, …` — the exact defect the reviewer saw.
- [x] Uncited factual answers are converted to a concise no-answer instead of being shown ungrounded. Only grounded, cited answers are cache-eligible.
- [x] Migration `0014` stores `source_chunk_ids` on both caches so a cache hit rebuilds the reference list its superscripts point at.
- [x] **UI1** Both chat surfaces audited, rebuilt, and confirmed non-stale.
- [x] **UI2** Active nav state from the route pathname; hamburger drawer at `<=1024px` with `aria-expanded`/`aria-controls`, Escape, close-on-navigate, and focus-visible rings. External links never claim active state.
- [x] **UI3** Loading row appears on submit; the in-flight guard blocks duplicate sends; honest error copy on failure.
- [x] **UI4** Answers render as inert text with paragraphs/bullets, superscripts linked to a `Sources` list; no citations means no `Sources` heading.
- [x] `+` upload button on **both** chat surfaces at every viewport. Chainlit uses its documented `[[UI.header_links]]` component.
- [x] User-facing copy rewritten in plain language; jargon guards added in backend, frontend, and Chainlit tests.
- [x] "Document still being prepared" separated from "no documents yet".
- [x] 17-test RAG system integration suite over a real multi-document corpus.
- [x] Assumptions documented (`README.md`, `ARCHITECTURE (4).md` §21); trade-offs in §18; `DEPLOYMENT.md` extended with cloud-provider choice, CI/CD strategy, observability, DR, and cost.

### Defects found and fixed during verification
- Deterministic generation client opened every answer with the document filename.
- Off-corpus questions ("snake bite") returned a confident, correctly-cited answer about malaria — retrieval's nearest neighbour was always quoted back, and lexical grounding could not catch it because the sentence really was verbatim from a source.
- Cached answers kept their superscripts but lost their sources, rendering a dangling citation.
- The mobile menu scrim was exposed as a second button with the same label as the toggle (duplicate a11y control).
- A hand-rolled Chainlit floating upload button collided with Chainlit's own header link at 1440 px — caught by screenshots, not assertions; replaced with the documented component.

### Verification
- [x] `docker compose -p assessment exec backend pytest` -> `161 passed, 12 skipped, 4 warnings in 62.95s`
- [x] `docker compose -p assessment exec backend pytest app/tests/test_rag_system_integration.py` -> `17 passed`
- [x] `npm test --prefix frontend -- --runInBand` -> `21 passed`
- [x] `npx tsc --noEmit` (frontend) -> clean
- [x] `python3 -m unittest chainlit_app.tests.test_chat` -> `10 passed`
- [x] `npx playwright test e2e/chat-ui.spec.ts` -> `16 passed` (real Chromium, both surfaces, 375/768/1024/1440)
- [x] Both `http://localhost:3000/` and `http://localhost:8000/` checked live and screenshotted
- [ ] `e2e/upload-chainlit-citation.spec.ts` live ingestion round trip
- [ ] Clean-clone dry run
- [ ] Real gold manual/CI score runs (corpus fetch/checksum/indexing/human verification still pending)

---

## Completed Cycles
- [x] **BC0 - Verify Starter Repo Integrity**
- [x] **BC1 - Scaffolding & Multi-Agent Orchestration Commit**
- [x] **BC2 - Database Schema & Alembic Migrations**
- [x] **BC3 - PDF Upload Endpoint & Validation Limits**
- [x] **BC4 - Structure Detection & Page Rasterization**
- [x] **BC5 - Chunking & Embeddings**
- [x] **BC6 - Ingestion Agent: Bounded Tool-Use Loop**
- [x] **BC7 - Retrieval: Vector Search, Lexical Search, and Hybrid Fusion**
- [x] **BC8 - Reranking: Local Cross-Encoder Confidence Signal**
- [x] **BC9 - Retrieval Agent: Confidence Gate, Query Expansion, and Page Image Fetch**
- [x] **BC10 - Orchestrator: Retrieval-Agent Tool Boundary and Generation Assembly**
- [x] **BC11 - Exact/Semantic Cache and Cache Hygiene Scheduler**
- [x] **BC12-BC15 - Chat, Documents UI, Guardrails, Auth, and Rate Limiting**
  - Pushed commit: `8ef6666 feat: implement BC12-BC15 chat documents guardrails auth`
  - Source branch: `codex/bc12-bc15-chat-documents-guardrails-auth`
  - PR creation URL: `https://github.com/Jungletrees/Senior-Engineer-AI-Digital-Health-Skills-Assessment/pull/new/codex/bc12-bc15-chat-documents-guardrails-auth`
  - Merged into current branch: `codex/bc16-bc28-final-tests-deploy-grading-correctives`

---

## BC9 - Retrieval Agent: Confidence Gate, Query Expansion, and Page Image Fetch

**Status:** [x] Completed

### Objective
Wire BC7 hybrid search and BC8 reranking into a bounded Retrieval Agent cascade that uses deterministic retrieval by default and expands queries only when reranker confidence is low.

### Completed Work
- [x] Added `backend/app/agents/retrieval_agent.py` with `RetrievalAgent.run` and `run_retrieval_cascade`.
- [x] Added `backend/app/retrieval/expand_query.py` with strict JSON/Pydantic parsing and safe fallback to `[original_query]`.
- [x] Added `backend/app/retrieval/fetch_page_image.py` as an internal-only tool for final reranked chunks.
- [x] Extended `backend/app/retrieval/models.py` with typed expansion, page-image, and Retrieval Agent result models.
- [x] Added retrieval-agent settings for confidence threshold and max iterations.
- [x] Ensured the expansion gate uses `reranked.top_relevance_score`, never raw RRF `top_score`.
- [x] Added trace-context forwarding where tools support tracing.

### Verification
- [x] `docker compose -p assessment exec backend pytest app/tests/test_retrieval_agent.py -vv`
  - Result: `8 passed in 8.35s`

### PR Draft
- [x] `.codex/pull_requests/PR_BC9.md`

---

## BC10 - Orchestrator: Retrieval-Agent Tool Boundary and Generation Assembly

**Status:** [x] Completed

### Objective
Implement the Orchestrator boundary that consults the Retrieval Agent as its only retrieval surface, compacts retrieved context deterministically, and assembles a generation-ready payload with optional image blocks.

### Completed Work
- [x] Added `backend/app/agents/orchestrator.py` with `consult_retrieval_agent`, `assemble_generation_payload`, and `RetrievalUnavailableError`.
- [x] Added deterministic `compact_chunk` in `backend/app/retrieval/compaction.py`.
- [x] Assembled stable system prefix, `<context source="..." page="...">...</context>` blocks, optional image blocks for multimodal models, and the user question last.
- [x] Added prompt-cache control integration on the stable system block.
- [x] Added explicit output-filter stub comment for BC14 replacement.
- [x] Added static import-boundary coverage proving the Orchestrator does not import retrieval internals or database access directly.

### Verification
- [x] `docker compose -p assessment exec backend pytest app/tests/test_orchestrator.py -vv`
  - Result: `9 passed in 0.82s`

### PR Draft
- [x] `.codex/pull_requests/PR_BC10.md`

---

## BC11 - Exact/Semantic Cache and Cache Hygiene Scheduler

**Status:** [x] Completed

### Objective
Implement exact-cache lookup/write, semantic-cache lookup/write, prompt-cache control, and a lightweight cache hygiene scheduler for TTL expiry, semantic LRU cap enforcement, and document-deletion invalidation.

### Completed Work
- [x] Added `backend/app/cache/` modules for exact cache, semantic cache, cache hygiene, and cache-first answer orchestration.
- [x] Implemented exact query normalization and SHA-256 normalized-query hashing.
- [x] Implemented semantic cache lookup with existing embedding client/dimension guard and pgvector cosine similarity.
- [x] Updated semantic hits to increment `hit_count` and refresh `last_used_at`.
- [x] Added `eligible: bool` gates to exact and semantic cache writes with BC14 TODO wiring.
- [x] Added `backend/app/scheduling/cache_scheduler.py` and FastAPI lifespan startup/shutdown wiring gated by `ENABLE_SCHEDULED_JOBS`.
- [x] Added `SEMANTIC_CACHE_MAX_ROWS=5000` to `.env.example`.

### Verification
- [x] `docker compose -p assessment exec backend pytest app/tests/test_cache.py -vv`
  - Result: `9 passed in 7.74s`
- [x] `docker compose -p assessment exec backend pytest`
  - Result: `64 passed, 12 skipped, 4 warnings in 20.89s`

### PR Draft
- [x] `.codex/pull_requests/PR_BC11.md`

---

## Architecture Decisions Logged
- [x] `ARCHITECTURE (4).md` section 18 records internal-only page-image access.
- [x] `ARCHITECTURE (4).md` section 18 records deterministic lexical-overlap context compaction.
- [x] `ARCHITECTURE (4).md` section 18 records BC11 scheduler infrastructure extended by BC20.
- [x] `ARCHITECTURE (4).md` section 18 records cache write eligibility gates.
- [x] `ARCHITECTURE (4).md` section 18 records cache invalidation by missing referenced document IDs.

---

## Active Cycle: BC16-BC28

**Status:** [x] Corrective implementation and deterministic verification completed; superseded by the Production Gap Closure cycle for Chainlit wiring, upload enqueueing, citation rendering, and Playwright scaffold. Gold manual/CI runs still require corpus fetch/checksum pinning plus human expected-answer verification before scores are meaningful.

### Objective
Complete the BC16-BC20 final test/deployment/docs/scheduler scope and BC21-BC28 corrective scope without restarting from scratch. This includes deterministic/gold-set test consolidation, frontend/Playwright coverage, deploy hardening, singleton scheduled jobs, cost/rate-limit/cache correctness, numeric-aware grounding, reproducible `JudgeAgent` grading, fixed gold-standard corpus evaluation, deviation alerts, and documentation fold-back.

### Planned Work
- [ ] **BC16:** Consolidate deterministic backend/golden-set tests; add `golden_set` pytest marker and retrieval-mode/cache/grounding report caveat.
- [ ] **BC17:** Complete frontend deterministic tests and Playwright smoke workflow; document `PLAYWRIGHT_BASE_URL` in README, not `.env.example`.
- [ ] **BC18:** Add/verify `/health`, production Docker system packages, S3 storage backend via IAM/task role, and CI jobs with deploy gated via real `needs:`.
- [ ] **BC19:** Fold README/local setup/test documentation back; add cross-link/env-var audit scripts and public tool docstring drift pass.
- [ ] **BC20:** Extend the existing scheduler with nightly grading, anomaly detection, config drift checks, and hour-of-day baseline guards.
- [x] **BC21:** Add Postgres advisory-lock scheduler singleton guard with per-job-family lock offsets.
- [x] **BC22:** Finish model-pricing cost computation, rate-limit indexes, semantic-cache `embedding_model` scoping, and drift invalidation.
- [x] **BC23:** Finish numeric-aware grounding and use the same implementation for pre-send filtering, nightly re-check, and gold grading; generated-output numeric claims are exact-match only.
- [x] **BC24:** Split anomaly cadence, store judge metadata, add Chainlit step shim tests, make tsvector config explicit, assert `SET LOCAL hnsw.ef_search` transaction scope, and keep duplicate idempotency polling pool-safe.
- [x] **BC25:** Integrate the gold-standard corpus/question/rubric package with TOFU checksums, verified-question skipping, and fixed rubric weights.
- [x] **BC26:** Persist `gold_eval_run` / `gold_eval_result`; add manual/CI runner through `/chat`; use fake chat and fake `JudgeAgent` clients in deterministic tests.
- [x] **BC27:** Add Markdown reports, category scores/trends foundation, deviation alerts, and baseline-reset behavior.
- [x] **BC28:** Fold BC21-BC27 decisions/docs/env/PR descriptions/handover into the canonical repo documentation.

### Expected Test Coverage
- [x] `docker compose -p assessment exec backend pytest app/tests/test_scheduler_singleton.py -vv`
- [x] `docker compose -p assessment exec backend pytest app/tests/test_cost.py -vv`
- [x] `docker compose -p assessment exec backend pytest app/tests/test_rate_limit_indexes.py -vv`
- [x] `docker compose -p assessment exec backend pytest app/tests/test_semantic_cache_model_scope.py -vv`
- [x] `docker compose -p assessment exec backend pytest app/tests/test_numeric_grounding.py -vv`
- [x] `docker compose -p assessment exec backend pytest app/tests/test_anomaly_detection.py -vv`
- [x] `docker compose -p assessment exec backend pytest app/tests/test_judge_reproducibility.py -vv`
- [x] `docker compose -p assessment exec backend pytest app/tests/test_gold_standard.py -vv`
- [x] `docker compose -p assessment exec backend pytest -m golden_set -vv`
- [x] `docker compose -p assessment exec backend pytest`
- [x] `npm test --prefix frontend -- --runInBand`
- [ ] `npx playwright test --prefix frontend` - not run; frontend has no Playwright dependency/config/spec yet.
- [ ] `python -m gold_standard.runner --trigger manual --sample 8` - pending corpus fetch/checksum pinning, indexing, and expected-answer verification.
- [ ] `python -m gold_standard.runner --trigger ci --floor 85` - pending corpus fetch/checksum pinning, indexing, and expected-answer verification.

### Verification Status
- [x] `python3 -m compileall backend/app gold_standard`
  - Result: passed in the handoff state.
- [x] `docker compose -p assessment build backend`
  - Result: passed. Fixed by pinning CPU-only `torch==2.9.1+cpu` from the official PyTorch CPU wheel index before `sentence-transformers`, keeping the local CrossEncoder architecture while avoiding the CUDA wheel chain that failed earlier.
- [x] `docker compose -p assessment up -d backend frontend`
  - Result: passed after backend image packaging was changed to include `gold_standard/` and `pytest.ini`.
- [x] `docker compose -p assessment exec backend pytest`
  - Result: `120 passed, 12 skipped, 4 warnings in 41.03s`.
- [x] `npm test --prefix frontend -- --runInBand`
  - Result: `1 passed`.
- [x] backend health smoke
  - Result: `{"status":"ok","database":"ok"}`.

### Current Partial Implementation
- [x] BC20-BC28 settings fields added in `backend/app/settings.py`.
- [x] `backend/app/core/cost.py` added and `/chat` cost finalization started.
- [x] Duplicate idempotency polling changed to roll back before sleeping so it does not hold a database connection.
- [x] Semantic cache lookup/write scoped by embedding model with migration/model/test coverage.
- [x] `backend/alembic/versions/0013_corrective_grading_schema.py` added for corrective schema changes.
- [x] `backend/app/agents/judge_agent.py` added as the production `JudgeAgent` boundary with injectable client and deterministic fallback.
- [x] `backend/app/security/numeric_grounding.py` added and `guardrails.py` wired to fail unsupported clinical numeric claims.
- [x] `gold_standard/` package adapted to the repo-native `/chat`, SQLAlchemy persistence, `JudgeAgent`, reporting, and deviation-alert paths.

### Checklist Documentation Pass - 2026-07-14

- [x] Rewrote root `README.md` as reviewer-facing project documentation instead of starter assessment instructions.
- [x] Updated `tests-README.md` to distinguish implemented deterministic tests from planned Playwright e2e coverage.
- [x] Rewrote `frontend/README.md` and added `frontend/.env.local.example`.
- [x] Updated `local-setup.md`, `DEPLOYMENT.md`, `.env.example`, and `gold_standard/README.md`.
- [x] Updated `build-plans-architecture/ARCHITECTURE (4).md` with dependency/build reliability notes, current frontend/e2e status, AWS/Lambda/Bedrock deployment planning, and synced env appendix.
- [x] Added `build-plans-architecture/SUBMISSION_CHECKLIST_STATUS.md` with section-by-section complete/partial/not-complete status.
- [x] Replaced the backend home page content so the product-facing root no longer serves assessment instructions.
- [x] Updated `docker-compose.yaml` with allow-listed environment injection, database dependency ordering, and basic DB/backend health checks.
- [ ] Clean-clone dry run not performed in this buildrun.
- [ ] No tag, archive, or repository access-control changes performed in this buildrun.

---

## Active Cycle: Production Gap Closure

**Status:** [x] Targeted implementation and verification complete; Playwright browser run, clean-clone run, and real gold scoring remain pending.

### Objective
Close the explicit production gaps left after BC16-BC28: wire Chainlit to `/api/v1/chat`, return/render structured citation metadata, visibly enqueue ingestion from the upload route, scaffold Playwright e2e, keep real gold scores trust-gated, and keep the reviewer-facing docs honest about complete versus partial work.

### Completed Work
- [x] Upload route schedules `process_document` through a FastAPI background task after a successful new upload commit.
- [x] Duplicate indexed/processing uploads still short-circuit without scheduling duplicate ingestion.
- [x] `/api/v1/chat` returns structured citation metadata assembled from retrieved chunk metadata.
- [x] Chainlit calls `/api/v1/chat`, preserves backend session IDs, and renders answer-level superscript citation notes.
- [x] Next.js root page is a native updated reviewer console instead of a stale backend HTML proxy.
- [x] Next.js root chat and `/documents` calls are public local reviewer flows with no browser token or bearer header dependency.
- [x] Backend document upload/list/status/delete routes are public for local reviewer use; invalid/missing bearer headers do not produce 401s.
- [x] Playwright dependency/config/spec added for upload-to-indexed-to-Chainlit cited-answer smoke.
- [x] `.env.example`, compose, README, frontend README, local setup, tests guide, and checklist status updated for the new runtime wiring.

### Verification Status
- [x] `python3 -m compileall backend/app chainlit_app`
  - Result: passed locally.
- [x] `npm test --prefix frontend -- --runInBand`
  - Result: `1 passed` after removing document-route auth bootstrap.
- [x] `docker compose -p assessment up -d --build backend frontend`
  - Result: rebuilt and restarted backend/frontend successfully.
- [x] `docker compose -p assessment exec backend pytest app/tests/test_auth.py app/tests/test_documents.py -vv`
  - Result: `9 passed, 4 warnings in 6.62s` against the rebuilt backend image.
- [x] `curl -s -i http://localhost:6100/api/v1/documents`
  - Result: `200 OK` with `[]` and no token.
- [x] `curl -s -i -H 'Authorization: Bearer nope' http://localhost:6100/api/v1/documents`
  - Result: `200 OK` with `[]`, proving document routes ignore stale/invalid bearer headers.
- [x] `curl -s -i -X POST http://localhost:6100/api/v1/documents`
  - Result: `422 Unprocessable Entity` for missing file rather than `401 Unauthorized`, proving upload is no longer auth-gated.
- [x] `docker compose -p assessment exec backend alembic upgrade head`
  - Result: restored live stack schema after targeted tests that downgrade the shared test database.
- [x] Chainlit client test
  - Result: `python3 -m unittest chainlit_app.tests.test_chat -v` passed earlier in this production-gap pass.
- [ ] Playwright live smoke after rebuilt services and browser binary installation.
- [ ] Full backend/frontend verification after targeted fixes.
- [ ] Clean-clone dry run.
- [ ] Real gold manual/CI score runs remain untrusted until corpus fetch/checksum pinning, indexing, and human expected-answer verification are complete.
