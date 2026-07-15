# Submission Checklist Status

This audit corresponds to `LMH_Assessment_Submission_Checklist (2).md`. It records what is complete, what is partial, and what should not be claimed as complete.

## 0. Priority Requirements

| Area | Status | Notes |
|---|---|---|
| Chicago-style superscript citations | Complete | Generation emits `[cite:n]` markers; `backend/app/chat/response_presenter.py` validates them against backend candidates, places superscripts at the end of the sentence they support (multiple superscripts when a sentence draws on several sources), drops invalid markers, and builds the reference list from chunk metadata only. Rendered identically by both chat surfaces. 19 presenter tests + Playwright assertions. |
| Responsive PDF upload page | Complete | Next.js `/documents` plus a `+` upload button on both chat surfaces. Verified in real Chromium at 375x812, 768x1024, 1024x768, and 1440x900: no horizontal overflow, no clipped controls, no overlapping controls. |
| Scalable/secure/well-documented backend | Mostly complete | Async FastAPI/SQLAlchemy, upload validation, background ingestion enqueueing, JWT auth path, rate limits, caches, advisory-lock scheduler, OpenAPI, and docs. A 17-test integration suite exercises caching, cost, prompt-injection interception, rate limiting, compaction, and the sliding context window against a real corpus. Production queueing remains a future scale step. |

## 1. Repository Root

| Item | Status | Notes |
|---|---|---|
| `README.md` | Complete for current state | Rewritten as project documentation with setup, architecture, testing, limitations, AWS plan, CI/CD plan, dependency notes, and gold workflow. |
| `.env.example` | Complete for current backend settings | Added missing request-size and gold-eval threshold settings; frontend browser var lives in `frontend/.env.local.example`. |
| `.gitignore` | Complete | Covers env files, caches, build outputs, DB/data artifacts, generated gold reports, downloaded corpus PDFs, and local temp files. |
| `.github/workflows/ci.yml` | Complete | Cold `--no-cache` image builds from a clean checkout on a GitHub-hosted runner, full-stack bring-up, health wait (proves Alembic applies to an empty volume), offline-reranker assertion, backend + integration suites, Alembic down/up round trip, and Playwright across both chat surfaces. Gated by a `verified` job. |
| `docker-compose.yaml` | Partial | Defines `backend`, `frontend`, `chainlit`, and `relational_db`; now passes an allow-list of app environment variables, adds DB/backend health behavior, and orders services. It is still a development compose file, not production infrastructure. |
| `LICENSE` | Not present | No license file found in this repository. |
| `docs/` | Not present | Architecture and deployment docs are in root and `build-plans-architecture/`. |

## 2. Backend

| Area | Status | Notes |
|---|---|---|
| FastAPI app/router/middleware | Complete | `backend/app/main.py` wires routers, CORS, security middleware, and scheduler lifespan. |
| Settings and env config | Complete | `backend/app/settings.py` centralizes runtime configuration. |
| Async database sessions | Complete | `backend/app/database.py` uses async SQLAlchemy with pool settings outside tests. |
| ORM and Alembic schema | Complete | Documents, chunks, pgvector, page images, chat, caches, audit, trace, grading, anomaly, and gold-eval tables are implemented. |
| Upload API | Complete for local route contract | Validates/stores PDFs and schedules `process_document` as a FastAPI background task for new uploads; indexed duplicates short-circuit without duplicate enqueue. |
| Chat API | Backend complete | `/api/v1/chat` implements idempotency, cache lookup, retrieval/generation, filtering, audit, source chunk persistence, and structured citation metadata. |
| Health API | Complete | `/health` checks database connectivity. |
| Ingestion/retrieval/generation services | Mostly complete | Worker, chunking, embeddings, hybrid retrieval, rerank, and generation boundary exist. Hosted-provider calls are mocked/fallback in deterministic tests. |
| Backend tests | Complete for deterministic scope | Full backend run: `220 passed, 12 skipped, 4 warnings`. Adds provider rate-limit retry (`test_gemini_retry.py`, 5) and dynamic ingestion-agent routing (`test_ingestion_routing.py`, 7) since the previous pass. |

## 3. Frontend

| Area | Status | Notes |
|---|---|---|
| Documents page | Complete | `/documents` supports upload, progress, status polling with plain-language labels, and optimistic delete with rollback. Reachable from a `+` button on both chat surfaces at every viewport. |
| Chat UI | Complete on both surfaces | Next.js `/` and Chainlit `:8000` are both supported and behaviorally identical over `/api/v1/chat`. Active nav state, responsive hamburger drawer at `<=1024px`, and a loading row on submit. |
| Citation components | Complete | Superscripts render at the end of the sentence they support, are linked to their entry in the `Sources` list, and an answer with no citations renders no `Sources` heading. Answers are rendered as inert text, never HTML. |
| API client config | Complete | `NEXT_PUBLIC_API_BASE_URL` is supported and documented in `frontend/.env.local.example`. |
| Frontend tests | Complete for this scope | `npm test --prefix frontend` -> 23 passed; `tsc --noEmit` clean; Playwright `e2e/chat-ui.spec.ts` -> 16 passed in real Chromium across four viewports on both surfaces. |

## 4. Chainlit

| Area | Status | Notes |
|---|---|---|
| Container | Complete | `chainlit_app/Dockerfile` builds the service with `uv` dependency installation. |
| Backend integration | Complete for chat contract | `chainlit_app/app/chat.py` posts to FastAPI `/api/v1/chat`, preserves backend session IDs, and handles unavailable/in-flight responses. |
| Config/welcome docs | Complete | `.chainlit/config.toml` sets the theme, a `[[UI.header_links]]` "+ Upload PDF" button, and custom CSS; `chainlit.md` is the plain-language welcome page. |

## 5. CI/CD

| Area | Status | Notes |
|---|---|---|
| GitHub Actions | Complete for build/test | `.github/workflows/ci.yml` runs cold `--no-cache` image builds, full-stack bring-up, all four test suites, migration round trip, and Playwright, gated by a `verified` job. The deploy half of the pipeline is still design only. |
| Docker build | Verified cold | `docker compose build --no-cache backend` passes locally, and CI rebuilds every image with no cache from a clean checkout on a non-author machine. |
| Deployment | Planned, fully documented | `DEPLOYMENT.md` now covers cloud-provider choice with rationale and alternatives, target architecture, compute trade-offs, environments/config, a gated CI/CD strategy, observability SLOs, disaster recovery, cost model, and named open items. No live deployment or IaC exists. |

## 6. README Checklist

| Required topic | Status |
|---|---|
| Overview | Complete |
| Architecture summary | Complete |
| Local run instructions | Complete |
| Verification URLs | Complete |
| Testing instructions/results | Complete |
| Assumptions/limitations | Complete |
| Security posture | Complete |
| Scalability posture | Complete |
| Dependency/build notes | Complete |
| Production AWS plan | Complete as a plan |
| CI/CD plan | Complete as a plan |
| Gold-standard workflow | Complete with trust caveat |
| Citation/UI limitations | Complete |
| Playwright status | Complete |

## 7. Assumptions

**Status: Complete.** The brief asks for assumptions to be noted rather than left implicit. They are stated in two places: a reviewer-facing summary in [`README.md`](../README.md#assumptions), and the full list with reasoning in [`ARCHITECTURE (4).md` §21](<./ARCHITECTURE (4).md>), grouped as:

- **§21.1 Corpus and input** — PDF is the only accepted format; documents are text-bearing or OCR-able and predominantly English; a document is immutable once uploaded (cache invalidation depends on it); one shared corpus rather than per-user libraries.
- **§21.2 Answer behavior** — no answer is better than a guessed one; the model cites but the application writes the reference list; citations are sentence-granular; retrieved-and-cited does not by itself mean relevant; a document title is derived from its filename.
- **§21.3 Deployment and reviewer stack** — the local public/anonymous posture is not the production one; both chat surfaces are equivalent; ingestion is in-process and best-effort; users are not retrieval engineers, so internal vocabulary is treated as a leak.
- **§21 (original)** — system-level OCR/poppler binaries, multimodal generation model, unverified `search_result` blocks, starting-default thresholds, single-tenant scope, CPU-only reranker inference.

Environment/runtime assumptions also hold: model choices and pricing are env-driven, embedding model and dimension must match the schema (changing the model is a re-index, not a config flip), chunking defaults to 480 tokens with 15% overlap, retrieval is cosine pgvector plus RRF and rerank, upload limits are 65 MB / 700 pages / PDF-only, chat history persists in PostgreSQL, numeric claims must match the cited source exactly, and production deployment is AWS-planned but not live.

## 8. Submission Mechanics

| Item | Status | Notes |
|---|---|---|
| Fork lineage/visibility | Not verified | Requires GitHub-side inspection. |
| Incremental commits | Present historically | The checklist documentation buildrun was intentionally kept local until this reviewer-facing docs commit. |
| Secrets not committed | Mostly verified | File scan found placeholders and docs only; the Git remote URL contains a token locally, which is not a committed file. |
| Correct branch/link | Partial | Current branch is `codex/production-gap-closure`; default-branch submission state not verified. |
| No post-deadline changes | Not applicable here | Requires human submission timing control. |

## 9. Clean-Clone Dry Run

Not performed in this checklist buildrun. Do not claim clean-clone validation passed.

Required before final human submission:

```sh
git clone <fork-url> /tmp/verify-clone
cd /tmp/verify-clone
cp .env.example .env
docker compose -p assessment up -d --build
docker compose -p assessment exec backend alembic upgrade head
curl -s http://localhost:6100/health
docker compose -p assessment down -v
```

Manual UI checks should include upload, worker indexing, a grounded chat answer, an out-of-corpus refusal, citation footnotes, and responsive breakpoints at 375, 768, 1024, and 1440 px.

## 10. Repo Integrity and Access Control

Not fully performed because repository visibility/access settings require GitHub-side inspection. Local git status and remote freshness should be checked again after the production-gap closure commit is pushed.
