# Last Mile Health RAG Platform

This repository implements a pdf-document retrieval-augmented generation system for uploaded PDF guidance. The stack keeps the original service boundaries: a Next.js document-management frontend, a Chainlit chat container, a FastAPI backend, and PostgreSQL with pgvector for document, chunk, audit, cache, and evaluation data.

The backend is the source of truth for ingestion, retrieval, generation, guardrails, caching, scheduling, and gold-standard evaluation. Uploaded PDFs are validated and stored through the API, then the upload route visibly enqueues the ingestion worker to parse page metadata, chunk content, embed text, and index into PostgreSQL/pgvector. Chat requests run through input validation, exact/semantic cache lookup, hybrid retrieval, local cross-encoder reranking, optional query expansion, grounded answer generation, structured citation assembly, output filtering, and audit logging.

Answers are grounded in the uploaded documents and carry Chicago-style superscript citations at the end of each sentence they support, with a `Sources` list built from document metadata rather than model text. Two chat surfaces are supported and behave identically: Next.js on `:3000` and Chainlit on `:8000`. The gold-standard evaluation runs end-to-end against a deterministic generated corpus; scores are labelled with the judge used and are only Opus-comparable when an Anthropic key pins the Opus judge.

## Documentation Map

Where each piece of documentation lives, for quick navigation.

| Topic | Document | What's in it |
|---|---|---|
| **Start here** | [`README.md`](./README.md) (this file) | Overview, sitemap, test results, local run, testing, deployment plan, security/scalability, assumptions |
| Local run & environment | [`local-setup.md`](./local-setup.md) | Step-by-step setup and the environment/portability risks (disk, RAM, ports, arch, the pytest schema-drop) |
| Architecture & decisions | [`build-plans-architecture/ARCHITECTURE (4).md`](<./build-plans-architecture/ARCHITECTURE (4).md>) | Full ingestion→retrieval→generation walkthrough, the decision log, and the complete assumptions list (§21) |
| Production deployment | [`DEPLOYMENT.md`](./DEPLOYMENT.md) | Cloud-provider choice + rationale, CI/CD strategy, infrastructure, secrets management, observability, DR, cost |
| Testing — how & results | [`tests-README.md`](./tests-README.md) | Every test suite, exact commands, and last results (backend, frontend, Chainlit, Playwright, gold eval) |
| Gold-standard evaluation | [`gold_standard/README.md`](./gold_standard/README.md) | The deterministic multi-type corpus, the questions, how to run the eval, and the honest score caveats |
| Latest gold-eval report | [`gold_standard/gold_eval_report.md`](./gold_standard/gold_eval_report.md) | Committed report from the most recent run (overall + per-question) |
| Configuration & API keys | [`.env.example`](./.env.example) | Every backend/DB/provider variable, plus the API-key-by-agentic-task map and secrets posture |
| Frontend config | [`frontend/.env.local.example`](./frontend/.env.local.example) · [`frontend/README.md`](./frontend/README.md) | The single browser-facing base-URL var; frontend notes |
| Chainlit surface | [`chainlit_app/chainlit.md`](./chainlit_app/chainlit.md) | The plain-language Chainlit welcome page |
| Agent orchestration | [`agents.md`](./agents.md) | The multi-agent mesh, coordination, and development guidelines |
| Submission checklist audit | [`build-plans-architecture/SUBMISSION_CHECKLIST_STATUS.md`](./build-plans-architecture/SUBMISSION_CHECKLIST_STATUS.md) | Per-item pass/partial/not-done status against the assessment checklist |
| Build plans & handoffs | [`build-plans-architecture/`](./build-plans-architecture/) | The incremental build plans (BC-series) and engineering handoff prompts |

## Latest Test Results

Full commands and per-suite detail are in [`tests-README.md`](./tests-README.md); the gold run is in [`gold_standard/gold_eval_report.md`](./gold_standard/gold_eval_report.md).

| Suite | Command | Result |
|---|---|---|
| Backend (pytest) | `docker compose -p assessment exec backend pytest` | **224 passed, 12 skipped** |
| Frontend (node --test) | `npm test --prefix frontend` | **24 passed** |
| Chainlit client | `python3 -m unittest chainlit_app.tests.test_chat` | **10 passed** |
| Playwright e2e (real Chromium) | `npx playwright test e2e/chat-ui.spec.ts` | **16 passed** (both surfaces @ 375/768/1024/1440 px) |
| Gold eval (compact corpus) | `python -m gold_standard.runner --trigger manual` | **91.12 / 100** over 8 questions |

Gold eval by category: **dosing 100 · refusal 100 · semantic 100 · synthesis 88.75 · procedure 66.5**. Every precise lookup (table/numeric, OCR-only, low-lexical-overlap semantic, out-of-corpus refusal) scores 100; the cross-document synthesis question cites both source documents; prose questions earn honest partial exact-fact credit. The judge is the local Gemini fallback (logged and recorded in run metadata), **not** the pinned Anthropic Opus, so the number is not an Opus-comparable floor. One scheduler concurrency test is known-flaky under load (documented in `tests-README.md`); it is not a production defect.

## Reviewer Build Status

| Workstream | Status | Evidence / reviewer note |
|---|---|---|
| Backend deterministic suite | Verified complete | Full backend run: `224 passed, 12 skipped, 4 warnings`. |
| FastAPI health/docs | Complete | `/health` returns `{"status":"ok","database":"ok"}` in the last smoke test; OpenAPI is available at `/docs`. |
| Documents API validation/storage | Complete for local public route contract | Upload validation, storage, dedup, list, poll, delete, and background worker enqueueing are implemented without IAM/JWT gating; deterministic route tests assert public access plus worker scheduling for new uploads and no reschedule for indexed duplicates. |
| Ingestion worker | Verified complete in deterministic tests | Worker path indexes a `processing` document, persists chunks/page images, and marks it `indexed` under fake clients. |
| Backend `/api/v1/chat` | Verified complete for backend contract | Idempotency, rate limit, cache ordering, retrieval/generation, filtering, audit, `source_chunk_ids`, and structured citation metadata are tested. |
| Chat surfaces (Next.js + Chainlit) | Verified complete | Both are supported and behaviorally identical over the same `/api/v1/chat` contract. Verified in real Chromium at 375/768/1024/1440 px. |
| Response presentation | Verified complete | `backend/app/chat/response_presenter.py` owns every writing-style and citation rule; 19 deterministic tests. Answers never open with a filename and never expose internals. |
| Chicago superscript citations | Verified complete, per sentence | Generation emits `[cite:n]` markers; the presenter validates them against backend candidates, places superscripts at the end of the sentence they support, drops invalid markers, and builds the reference list from chunk metadata only. |
| RAG system integration | Verified complete | 17 tests over a real multi-document pgvector corpus covering synthesis, caching, cost, prompt injection, rate limits, compaction, and the sliding context window. |
| Frontend `/documents` UI | Verified complete | Upload, progress, polling, friendly status labels, optimistic delete with rollback. |
| Playwright e2e | Verified complete for the chat UI | `e2e/chat-ui.spec.ts` -> 16 passed in real Chromium. The upload-to-cited-answer spec still needs a live ingestion round trip. |
| Gold-standard workflow | Runs end-to-end on the compact corpus | A deterministic, generated 4-PDF corpus (table / hierarchy / prose / scanned-OCR) indexes and the eval scores **91.12/100** over 8 questions (table, semantic, hierarchy, OCR, cross-doc synthesis, refusal). The judge is the honest Gemini fallback, not the pinned Opus, so the number is not an Opus-comparable floor. The real ~659-page WHO corpus needs a paid/fresh-project embedding key. |
| Clean-clone validation | Not complete | A clean clone has not been run for this checklist pass. |
| AWS deployment | Planned | AWS architecture, Lambda/Bedrock rationale, security, and CI/CD plan are documented; no live deployment or IaC exists. |

## Assumptions

The brief invites noting assumptions rather than leaving them implicit. These are the ones this build makes; the full list, with reasoning, is in [ARCHITECTURE (4).md §21](<./build-plans-architecture/ARCHITECTURE (4).md>).

**Input**

- **PDF is the only accepted format.** Upload validation checks PDF magic bytes and the MIME allow-list; ingestion, page rasterization, OCR fallback, and page-number citations are all built around a paginated document. Other formats are rejected at the API boundary rather than partially supported.
- **Documents are text-bearing or OCR-able, and predominantly English.** Full-text search uses PostgreSQL's `english` configuration, so stemming assumes English. A PDF that is neither extractable nor OCR-able yields "I could not find that in your documents" rather than a wrong answer.
- **A document is immutable once uploaded.** Re-uploading a changed file creates a new document id. Cache invalidation depends on this.
- **One shared corpus, not per-user libraries.** Every uploaded document is visible to every chat session on the instance.

**Answers**

- **No answer is better than a guessed one.** This is clinical guidance, so an invented dose is worse than an admission of ignorance. An answer whose citations do not survive validation becomes a concise no-answer, and numeric claims must match the cited source exactly (tolerance `0.0`) or they are filtered.
- **The model cites; the application writes the reference list.** Generation emits `[cite:n]` markers pointing at context blocks the backend supplied. Titles, page numbers, and reference entries come from chunk metadata only, so the model cannot invent a source or a page. Markers referencing unknown ids are dropped.
- **Retrieved-and-cited does not mean relevant.** Lexical grounding proves an answer's words came from a source, not that the source answers the question — a "snake bite" question can truthfully quote a malaria document. Relevance is checked separately, and grounding alone is not treated as sufficient.
- **A document title is derived from its filename**, so a poorly named upload produces a poorly named reference.

**Deployment**

- **The local reviewer stack is not the production security posture.** Document routes are public and chat is anonymous so the stack runs without provisioning auth. The JWT path still exists and is tested; production is assumed to enable it and scope documents per tenant.
- **Ingestion is in-process and best-effort.** Upload enqueues a FastAPI background task, not a durable queue, so a restart mid-ingestion leaves a document in `processing` and it must be re-uploaded. A queue-backed worker is the named production replacement.
- **Users are not retrieval engineers.** User-visible copy never mentions chunks, indexes, retrieval modes, or grounding; internal vocabulary is treated as a leak and is enforced against by tests.

**Environment** — full table with mitigations in [local-setup.md](./local-setup.md#environment-requirements-and-known-portability-risks)

- **~10 GB free disk, 4 GB free RAM, and network for the first build.** Images total ~5.7 GB (backend is 2.92 GB, dominated by torch); a measured cold `--no-cache` backend build took **20m 01s**. Runtime memory is small (~450 MB across all containers). No GPU is used.
- **Ports 3000, 5432, 6100, 8000 must be free.** 5432 is the realistic collision, with a developer's own PostgreSQL.
- **x86_64 and arm64 are both supported, but only x86_64 has been executed.** `torch==2.9.1+cpu` exists only for x86_64, so the pin is now architecture-conditional; the arm64 path is a reasoned fix, not a verified one.
- **Running `pytest` drops the database schema.** The test fixtures run Alembic **down to `base`** against the same database the running stack uses and then back up, and the final teardown leaves it downgraded — so after a test run **every table is dropped** (all uploaded documents, chunks, caches, and audit rows are gone, and `/chat`/uploads will error with `relation "documents" does not exist`). This is by design for test isolation, but it means you must **restore the schema before using the app again**:

  ```sh
  docker compose -p assessment exec backend alembic upgrade head
  docker compose -p assessment restart backend   # clears asyncpg prepared-statement caches
  ```

  The restart matters: recreating the schema under a running backend leaves its asyncpg connection pool holding prepared statements bound to the dropped tables, and the next ingestion fails with `InvalidCachedStatementError` until the pool is refreshed. After the restart, re-upload your documents. For this reason, do not run the full `pytest` suite against a stack you are actively demoing.
- **A green local run is not evidence of portability.** A warm Docker cache hides the failures a reviewer hits first, which is why CI builds every image `--no-cache` from a clean checkout.

## Chat Surfaces

Both chat surfaces are supported, which the starter explicitly allows ("may be used in place of or alongside the Next.js frontend").

| Surface | URL | Role |
|---|---|---|
| Next.js chat | http://localhost:3000/ | Full chat workspace with document navigation, a `+` upload button, and a responsive sidebar |
| Chainlit chat | http://localhost:8000/ | Equivalent chat surface with a `+ Upload PDF` header button |
| Upload page | http://localhost:3000/documents | The single ingestion entry point; both chat surfaces link to it |

Neither client implements retrieval, generation, or citation logic. Both call `/api/v1/chat` and render the same presented answer and the same source list, so a behavioral difference between them is a bug, not a feature of one surface. Use whichever you prefer.

## Architecture Summary

```text
Next.js :3000 /documents
        |
        | PDF upload, document list/delete
        v
FastAPI :6100 /api/v1
        |-- auth/session, documents, chat, config, health, OpenAPI docs
        |-- upload validation, ingestion, OCR/rasterization, chunking
        |-- exact cache, semantic cache, hybrid search, rerank
        |-- guardrails, numeric grounding, audit logs, scheduled jobs
        v
PostgreSQL :5432 + pgvector
        |-- documents, chunks, page_images, chat_messages
        |-- query_audit_log, agent_trace_log, response_grade
        |-- gold_eval_run, gold_eval_result, anomaly_flag

Chainlit :8000
        |-- posts to FastAPI /api/v1/chat and renders citation notes
```

Core backend components:

- **Frontend:** Next.js `/documents` page for PDF upload, client-side validation, progress display, document polling, and delete.
- **Chat UI:** Chainlit calls the backend chat API, keeps the returned session ID, and renders answer-level citation notes.
- **Backend:** FastAPI with async SQLAlchemy sessions, CORS/security middleware, optional JWT session tokens for closed-chat mode, rate limits, and OpenAPI at `/docs`.
- **Database:** PostgreSQL 16 with pgvector, HNSW vector index, generated `content_tsv`, and Alembic migrations.
- **Retrieval:** vector search plus PostgreSQL full-text search, Reciprocal Rank Fusion, local `sentence-transformers` CrossEncoder reranking, and gated query expansion.
- **Generation:** backend `/api/v1/chat` assembles grounded context and returns `source_chunk_ids` plus structured citation metadata for clients.
- **Guardrails:** input validation, prompt-injection delimiter sanitization, output grounding checks, exact numeric/dosage grounding, and cache write eligibility.
- **Caches:** exact normalized-query cache and semantic cache scoped by embedding model.
- **Scheduler:** cache hygiene, retrospective grading, anomaly detection, and gold-eval jobs guarded by PostgreSQL advisory locks.
- **Gold evaluation:** versioned corpus/question/rubric workflow with checksum pinning, verified-answer skipping, SQL persistence, Markdown reports, and deviation alerts.

## Local Setup

Prerequisites:

- Docker Engine 24+ and Docker Compose v2+
- Node 20+ only if running frontend commands outside Docker
- Python 3.12 only if running backend or gold-standard commands outside Docker

Start the full local stack:

```sh
cp .env.example .env
docker compose -p assessment up -d --build
```

Run migrations if the database volume is new or has been reset:

```sh
docker compose -p assessment exec backend alembic upgrade head
```

Stop the stack:

```sh
docker compose -p assessment down
```

Service URLs:

| Service | URL | Notes |
|---|---|---|
| Frontend | http://localhost:3000 | Root status page and `/documents` UI |
| Documents page | http://localhost:3000/documents | Public local upload/list/status/delete UI; no browser token required |
| Chainlit | http://localhost:8000 | Chat UI wired to backend `/api/v1/chat` |
| Backend | http://localhost:6100 | FastAPI app |
| Backend health | http://localhost:6100/health | Returns database health |
| Backend docs | http://localhost:6100/docs | OpenAPI docs |
| PostgreSQL | localhost:5432 | `pgvector/pgvector:pg16` |

Document-management endpoints are intentionally public for the local reviewer stack and do not require IAM, hosted auth, or a JWT:

```sh
curl -s http://localhost:6100/api/v1/documents
```

The `/api/v1/auth/session` endpoint remains available only for optional closed-chat mode. Chat is anonymous when `ANONYMOUS_CHAT_ALLOWED=true`; set it to `false` to require a bearer token for `/api/v1/chat`.

## Verification

Basic smoke checks:

```sh
docker compose -p assessment ps
curl -s http://localhost:6100/health
curl -I http://localhost:6100/docs
curl -I http://localhost:3000
curl -I http://localhost:3000/documents
curl -I http://localhost:8000
```

Last known green verification:

```text
docker compose -p assessment exec backend pytest
224 passed, 12 skipped, 4 warnings

npm test --prefix frontend
23 passed

python3 -m unittest chainlit_app.tests.test_chat
10 passed

npx playwright test e2e/chat-ui.spec.ts   (real Chromium, both chat surfaces)
16 passed

backend health smoke
{"status":"ok","database":"ok"}
```

Run the deterministic suites:

```sh
docker compose -p assessment exec backend pytest
npm test --prefix frontend
```

Run Playwright smoke after the stack is rebuilt and Playwright browser binaries are installed:

```sh
npm --prefix frontend run playwright:install
PLAYWRIGHT_BASE_URL=http://localhost:3000 npm --prefix frontend run test:e2e
```

## Dependency and Build Reliability Notes

The backend Docker build had two dependency failures that are now documented and repaired:

- `docker-compose.yaml` passes an explicit allow-list of application environment variables into containers rather than injecting every key from the local `.env` file. This avoids accidentally exposing unrelated developer secrets to app containers.
- Initial pip cache/hash corruption was addressed by removing the Docker pip cache mount and installing with:

  ```dockerfile
  RUN pip install --no-cache-dir --default-timeout=180 --retries=10 -r /requirements.txt
  ```

- A later empty wheel payload/hash error occurred during the large `sentence-transformers` / torch dependency chain. The architecture-safe fix was to pin CPU-only `torch==2.9.1+cpu` through the official PyTorch CPU wheel index before installing `sentence-transformers`. This preserves the local CrossEncoder reranking architecture while avoiding CUDA wheel downloads and reducing image fragility, size, and cost.
- The backend Docker build context is the repository root. `.dockerignore` keeps the context small while allowing `backend/`, `gold_standard/`, and `pytest.ini` into the image so scheduled gold evaluation imports work in production-like containers.
- `poppler-utils` and `tesseract-ocr` are runtime system packages, not Python dependencies. They are installed in the backend image for PDF rasterization and OCR fallback.
- Chainlit dependency resolution is intentionally handled with `uv pip install` in `chainlit_app/Dockerfile` to avoid very slow pip resolver backtracking in the Chainlit/OpenTelemetry dependency tree. `httpx` is an explicit Chainlit dependency because the chat UI now calls FastAPI directly.

## Gold-Standard Evaluation

The `gold_standard/` package exercises the real `/api/v1/chat` path, stores runs/results, writes a Markdown report, and can alert on score deviations.

One-time setup and verification:

```sh
python -m gold_standard.fetch_corpus
python -m gold_standard.verify_expected --search
```

Manual and CI-style runs:

```sh
python -m gold_standard.runner --trigger manual --sample 8
python -m gold_standard.runner --trigger ci --floor 85
```

Do not trust gold scores until the corpus PDFs have been fetched, SHA-256 hashes are pinned in `gold_standard/corpus/corpus_manifest.yaml`, source documents are indexed into the local app, and expected answers have been human-verified. PDFs and generated reports are ignored and must not be committed.

## Security Posture

### API keys by agentic task

Each agent in the pipeline chooses its provider from the cheapest **configured** key that suits its task (`backend/app/core/model_router.py`). The one exception is the JudgeAgent, which is **pinned to Anthropic Opus** and never cost-routed, because a grader must be stable across runs.

| Agent / task | Key it uses (cost order) | Local default model | Rationale |
|---|---|---|---|
| Answer generation (`/chat`) | `GEMINI` → `OPENAI` → `ANTHROPIC` | `gemini-3.1-flash-lite` | Cheapest capable model; answer quality is the product |
| Embeddings (semantic search) | `GEMINI` → `OPENAI` → `VOYAGE` | `gemini-embedding-001` (1536-dim) | Must match `EMBEDDING_DIM`; changing it is a re-index |
| Fast/mechanical (summaries, query expansion, planning) | `GEMINI` → `OPENAI` → `ANTHROPIC` | `gemini-3.1-flash-lite` | Cheapest small model; paying Opus rates here is waste |
| Ingestion planning (ingestion agent) | `GEMINI` → `OPENAI` → `ANTHROPIC`, else deterministic | cheapest suited (`gemini-3.1-flash-lite`) | Sequences the page-structure tools. Requires no specific vendor key: routes to the cheapest available provider, and with no key runs the identical deterministic per-page path — the tools are local, so the choice never changes extraction quality |
| **JudgeAgent (grading, gold eval)** | **`ANTHROPIC` only** | **`claude-opus-4-8`** | **Pinned, not cost-routed.** A non-Opus judge is logged and its scores are marked not comparable to an Opus-judged baseline |

`MODEL_ROUTING=auto` (default) picks the cheapest suited provider per task; `MODEL_ROUTING=manual` honors the pinned `GENERATION_MODEL_PRIMARY`/`_FAST`. The provider is derived from the model name plus which keys are real (`gemini-*` → `GEMINI_API_KEY`, `claude-*` → `ANTHROPIC_API_KEY`, `gpt-*`/`text-embedding-*` → `OPENAI_API_KEY`, `voyage-*` → `VOYAGE_API_KEY`).

**With no key**, the system degrades and says so (a `model_status` notice in both chat UIs, plus an audit-log row). A reviewer judging answer quality needs at least a generation key and an embedding key; a gold-eval score needs an Anthropic key for the pinned Opus judge, or its metadata records that a fallback judge scored it. Full per-key detail is in `.env.example`.

#### Provider rate limits and the free-tier embedding cap (read before ingesting a large PDF)

Hosted providers rate-limit requests, and ingestion is embedding-heavy: a multi-hundred-page PDF produces hundreds of chunks, each an embedding request. The backend handles this in two layers, both env-tunable:

- **Retry with backoff.** A transient `429`/`5xx` from Gemini is retried with exponential backoff up to ~2 minutes (`_gemini_post_with_retry`), honoring any `Retry-After`. A real `4xx` (e.g. a malformed request) is never retried. Covered by `test_gemini_retry.py`.
- **Batch + pacing.** `batchEmbedContents` counts each item in the batch as one request against the per-minute quota, so a batch at the API ceiling (100) exhausts a whole minute in one call. The batch is capped (`EMBEDDING_BATCH_LIMIT=40`) and batches are paced to stay under `EMBEDDING_REQUESTS_PER_MINUTE=70`. Raise both — or set the RPM to `0` to disable pacing — on a paid tier.

**The hard limit is the free-tier _daily_ embedding quota, not the per-minute one.** Gemini's free tier for `gemini-embedding-001` enforces `EmbedContentRequestsPerDayPerUserPerProjectPerModel`, a low per-day cap that is **per Google Cloud project** (rotating to another key on the same project does not reset it). When it is exhausted, every embedding request returns `429` regardless of backoff, and the document ends in `failed` — this is an account quota, not a code fault. To ingest the full corpus on a free tier, use a key from a **fresh project** (fresh daily quota), enable billing to lift the cap, or wait for the daily reset. Generation and embedding quotas are separate buckets, so chat can keep working even when embedding is capped. If you only need to see the pipeline run end-to-end without a key, unset the embedding key and the system indexes with the offline hash-based embedder and shows the "limited search" notice.

### API keys — security posture

Provider keys are the highest-value secret here — they are spendable. Full posture in [DEPLOYMENT.md § Secrets and API Key Management](./DEPLOYMENT.md); the rules that shape the code:

- **Only the backend ever holds a provider key.** The browser never sees one, and no key exists in any frontend bundle (`frontend/.env.local.example` holds a base URL and nothing else). Both chat surfaces call `/api/v1/chat`; the backend makes every provider call server-side.
- **No key may be prefixed `NEXT_PUBLIC_`.** Next.js inlines those into the client bundle at build time, publishing them to every visitor. That would be an incident, not a bug.
- Keys are read from the environment only. They are never written to the database, never returned by any route, and never logged — provider-selection logs name the *variable*, never the value (`generation.provider_key_missing key=ANTHROPIC_API_KEY fallback=deterministic`).
- **Placeholders degrade safely.** `your-anthropic-api-key-here` is detected as *absent*, so an unedited `.env` falls back to the local path instead of 401-ing on every chat turn.
- **A missing key degrades; it never crashes.** With no generation key configured, answers come from a local extractive fallback; with no embedding key (`GEMINI`/`OPENAI`/`VOYAGE`) embeddings are a hash-based fallback and **semantic search is effectively off**. Both are documented in `.env.example`, because a reviewer judging answer quality needs to know which path they are on.
- In production, keys come from Secrets Manager/SSM injected at task start — never baked into an image, never a committed `.env` — with per-environment keys, scheduled rotation, a provider-side spend cap, and CI secret scanning.

### Everything else

- No real secrets are committed; `.env.example` uses placeholders.
- Document-management endpoints are public for the local reviewer stack; optional JWT session tokens are retained only for closed-chat mode when anonymous chat is disabled.
- Upload validation checks PDF magic bytes, parsed page count, MIME allow-list, and size limits before persistence.
- CORS is environment-driven through `CORS_ALLOWED_ORIGINS`; production should use explicit origins only.
- Database access uses SQLAlchemy/parameterized SQL. The pgvector/full-text retrieval SQL is written with bound parameters.
- Rate limits are enforced per session and per IP from `query_audit_log`, with indexes for the hot-path counts.
- Generated answers pass lexical grounding and exact numeric/dosage grounding before cache eligibility.
- Production storage should use S3 private buckets with KMS encryption and IAM task/Lambda roles, not static AWS keys.

## Scalability Posture

- FastAPI request handling and database access use async SQLAlchemy sessions with a configured connection pool.
- Upload requests persist a document record and enqueue background ingestion; a durable queue is the production next step for high-volume PDF processing.
- The backend is stateless across replicas; session, cache, audit, grading, and trace data live in PostgreSQL.
- Scheduled jobs are protected by PostgreSQL advisory locks so horizontal replicas do not duplicate cache hygiene, grading, anomaly, or gold-eval jobs.
- Exact and semantic caches reduce repeated retrieval/generation work. Semantic cache rows are scoped by embedding model to avoid cross-model vector comparisons.
- For scale, move PDFs/page images to S3, use RDS Multi-AZ with backups, add RDS Proxy where Lambda is used, and move long-running ingestion to queue-backed workers.

## Current Limitations and Assumptions

- The Chainlit citation renderer uses answer-level superscript markers and notes from backend citation metadata. Per-sentence multi-source citation placement is not implemented.
- The upload route uses FastAPI background tasks for local/development ingestion. For production scale, replace that with S3/SQS/EventBridge or another durable queue-backed worker while preserving the same idempotent document state checks.
- Responsive UI verification has deterministic source tests, but no browser/device pass has been run in this checklist build. Breakpoints to verify manually are 375, 768, 1024, and 1440 px.
- Playwright e2e is scaffolded; execution requires installed browser binaries and the updated Docker stack running on ports 3000, 8000, 6100, and 5432.
- Gold-standard real scores are not trusted until corpus fetch, checksum pinning, indexing, and expected-answer verification are complete.
- Clean-clone validation has not been performed in this checklist build.
- AWS deployment is a documented production plan, not evidence of a live deployment.
- The default local embedding model is `text-embedding-3-small` with `EMBEDDING_DIM=1536`; schema and runtime settings must remain aligned.
- Retrieval defaults are `RETRIEVAL_TOP_K=20`, `RERANK_TOP_N=5`, cosine pgvector search, and RRF with `RRF_K=60`.

## Production AWS Deployment Plan

The target production architecture is AWS with private networking and managed data services:

- **Frontend:** S3 + CloudFront for a static export if the app is made static, or ECS Fargate/App Runner for the current Next.js server runtime.
- **Backend API:** ECS Fargate is the best fit for the current FastAPI container because local reranking, PDF parsing, OCR, and connection pooling benefit from warm containers.
- **Chainlit:** ECS Fargate behind the same ALB once it is wired to `/api/v1/chat`; otherwise omit it from production.
- **Database:** Amazon RDS PostgreSQL 16 with pgvector enabled, Multi-AZ, encrypted storage, automated backups, and restore testing.
- **Object storage:** S3 private buckets for uploaded PDFs and rasterized page images, encrypted with KMS.
- **Secrets:** AWS Secrets Manager or SSM Parameter Store injected at runtime. IAM roles provide S3/Bedrock access; no static AWS access keys.
- **Network boundary:** CloudFront/WAF plus ALB or API Gateway. Application tasks run in private subnets with security groups allowing database access only from backend tasks.
- **Observability:** CloudWatch logs, metrics, traces, dashboards, and alarms for p95 latency, 5xx rate, cache hit rate, grounding failures, cost spikes, anomaly flags, and gold-eval regressions.

Lambda is a strong fit for bursty, event-driven work: ingestion triggers, scheduled grading kicks, corpus-eval triggers, lightweight API handlers, and idle-cost-sensitive jobs. Lambda is not a good default for long-running local model inference, large PDF parsing/OCR, or heavyweight CPU/GPU workloads; those should stay on ECS/Fargate, move to Bedrock-hosted models, or run as managed async workers. If the API is split onto Lambda, use API Gateway + Lambda + RDS Proxy, provisioned concurrency for cold-start-sensitive routes, and keep local model inference out of the function path.

Compute trade-offs:

| Option | Best fit | Trade-off |
|---|---|---|
| Lambda | Bursty jobs, schedulers, lightweight handlers | Cold starts, timeout limits, RDS pooling needs RDS Proxy |
| ECS Fargate | Current containers, PDF/OCR, local reranker | Higher idle floor than Lambda |
| App Runner | Simple container deploys | Less network/control flexibility than ECS |
| EKS | Large multi-service platform | Operational overhead is not justified here |
| EC2 | Full host control | Manual patching/scaling burden |

Amazon Bedrock should be the production model-governance layer where available. Route cheap tasks such as summarization, classification, grading prechecks, and query expansion to fast/low-cost models; reserve stronger models for final grounded answer generation and complex clinical reasoning. Keep `JudgeAgent` reproducible with pinned model, temperature, and rubric version. Track per-model token usage and cost through `MODEL_PRICING_JSON` or a Bedrock-aware equivalent, add budget alerts/anomaly detection, use exact/semantic/prompt caching only after grounding/refusal gates, and preserve exact numeric grounding regardless of model choice.

## CI/CD Plan

CI is active: `.github/workflows/ci.yml` builds every image with `docker compose build --no-cache` from a clean checkout on a GitHub-hosted runner, brings the full stack up, waits for health (which also proves Alembic migrations apply to an empty volume), asserts the reranker loads offline from the image, then runs the backend suite, the RAG integration suite, an Alembic down/up round trip, and Playwright against both chat surfaces. A `verified` job gates on all of them.

This is what answers "will it build on the reviewer's machine" — a green local run does not, because a warm Docker cache hides missing architectures, missing system packages, and runtime model downloads.

CD is planned rather than active; there is no IaC and no target environment yet.

Recommended pipeline:

- PR checks: backend `pytest`, frontend `npm test`, lint/typecheck where configured, Docker backend build, Alembic migration check.
- Main branch deploy: use explicit `needs:` gates so deploy cannot run unless checks pass.
- Images: build and push backend/frontend/Chainlit images to ECR when containers are retained.
- Infrastructure: deploy VPC, RDS, S3, Secrets Manager/SSM, IAM, ALB/API Gateway, WAF, and CloudWatch with Terraform, CDK, or CloudFormation.
- Migrations: run Alembic as a one-off migration task before backend rollout; fail deployment on migration failure.
- Environments: dev, staging, prod with separate secrets and databases.
- Production release: manual approval, smoke tests after deploy (`/health`, minimal upload, minimal chat), and rollback to the previous image/task definition.
- Optional gate: once the corpus is pinned and expected answers are verified, enforce a gold-eval score floor before production promotion.

More detail is in [DEPLOYMENT.md](./DEPLOYMENT.md) and [build-plans-architecture/ARCHITECTURE (4).md](<./build-plans-architecture/ARCHITECTURE (4).md>).
