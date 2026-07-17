# Build Plan
### Last Mile Health — Senior Full-Stack Engineer, AI & Digital Health Practice Assessment

---

## 0. How to Use This Document

This is the execution companion to `ARCHITECTURE.md`. `ARCHITECTURE.md` is the single source of truth for **what** to build and **why**; this document is the single source of truth for **in what order**, **who builds it**, and **what "done" means at each step**. The three build agents (`agents/Frontend-engineer-SKILL.md`, `agents/Backend-engineer-SKILL.md`, `agents/ML-engineer-SKILL.md`) each own a disjoint slice of the cycles below — where a cycle is shared, both owning agents' files say so and this document names both.

Every cycle maps to one or more numbered sections of `ARCHITECTURE.md`. If a cycle's work would require deciding something `ARCHITECTURE.md` hasn't already decided, that's a stop-and-flag moment (per each agent's file, §7/§6/§7 respectively on "known documentation gaps") — not a silent design call made mid-cycle.

**Precondition chain:** cycles are numbered in dependency order. A cycle's own Definition of Done is the precondition for the next cycle that depends on it — this is stated explicitly per cycle below, not left implicit.

---

## 1. Scope of This Pass

This document currently specifies **BC0 through BC3** in full — the four cycles that take the project from "starter repo, unconfigured" to "a real PDF can be uploaded, validated, and accepted by a persisted schema." Cycles BC4 onward are named and scoped in each owning agent's `agents/*-SKILL.md` file (§8 of the backend and ML files, §7 of the frontend file) and will be expanded into this document's full per-cycle template in a subsequent pass — don't treat their absence here as "not yet decided," they're decided, just not yet written out at this document's level of detail.

---

## 2. Build Cycle → Requirement Traceability

| Build Cycle | Assessment Requirement(s) | Primary `ARCHITECTURE.md` §§ |
|---|---|---|
| BC0 | — (pre-req) | `local-setup.md`, §11.3 |
| BC1 | 6, bonus (arch doc) | §0, §22 |
| BC2 | 4 | §6, §18 |
| BC3 | 2 | §4.1, §4.2, §12.3 |
| BC4 | 3, bonus (ML justification) | §4.3, §15.2, §17 |
| BC5 | 3, 4 | §4.4, §6 |
| BC6 | 3, bonus (agent architecture) | §15.0–§15.2, §15.5, §15.9 |
| BC7 | 3 | §7.1, §7.2 |
| BC8 | 3, bonus (ML justification) | §7.3, §15.3, §17 |
| BC9 | 3, bonus (agent architecture) | §15.1, §15.3 |
| BC10 | 3 | §15.4, §15.5, §15.6 |
| BC11 | bonus (caching layer) | §9 |
| BC12 | 1 | §5, §12.2 |
| BC13 | 2 | §4.5 |
| BC14 | 3 (secure) | §12.1, §12.3, §12.4 |
| BC15 | 3 (secure) | §12.0, §13 |
| BC16 | 5 | §11.1, §11.2, §11.5 |
| BC17 | 5 | §11.3, §11.4 |
| BC18 | 7 | §19 |
| BC19 | 6, bonus (documentation) | §0, all |
| BC20 | bonus (retrospective grading, anomaly detection) | §6, §11.6, §20, §20.1 |

**Owning agent per cycle**, for the cycles specified in this pass and the near-term cycles that follow them:

| BC | Owner(s) |
|---|---|
| BC0 | Backend + Frontend (shared — each verifies their own containers) |
| BC1 | Backend |
| BC2 | Backend |
| BC3 | Backend |
| BC4 | ML (heuristic + threshold), Backend (loop/controller wiring) |
| BC5 | ML (chunking/embedding spec), Backend (deterministic-tail implementation) |
| BC6 | Backend |
| BC7 | ML (fusion spec), Backend (SQL/index implementation) |
| BC8 | ML |
| BC9 | ML (gating semantics), Backend (loop mechanics) |

---

## 3. How to Read Each Build Cycle

Every cycle below follows the same template:

- **Maps to** — the §2 cadence item (if any) and the `ARCHITECTURE.md` §§ it implements.
- **Objective** — one to two sentences.
- **Preconditions** — what must already be true (usually: the previous cycle's Definition of Done).
- **New/changed env vars** — only the incremental set this cycle introduces; the full `.env.example` is `ARCHITECTURE.md` §23.
- **Workflow** — the concrete steps, in order.
- **Architectural decisions & trade-offs invoked** — pointers into `ARCHITECTURE.md` §18's Decision Log, summarized in one line each so this document doesn't duplicate that table wholesale.
- **Tests to add this cycle** — unit, integration, and "other" (contract/migration/security) tests, written *in* this cycle, not deferred.
- **Definition of done** — a checklist; the precondition for the next cycle.
- **Suggested commit(s)** — using §22's `feat:`/`fix:`/`docs:`/`test:`/`chore:` convention.

---

## 4. Build Cycles

### BC0 — Verify the starter repo boots

**Maps to:** pre-requisite (no assessment requirement directly); `local-setup.md`, §11.3.
**Owner:** Backend + Frontend, shared — each agent verifies their own containers; neither proceeds to BC1/BC13 until this cycle's Definition of Done is a checked fact, not an assumed one.

**Objective:** Confirm the provided starter stack (Next.js, Chainlit, FastAPI, Postgres) boots cleanly as-is, before any code changes are made, and source or build the one required table-bearing test-fixture PDF that every later cycle's structure-detection and citation tests depend on.

**Preconditions:** None — this is the first cycle. Starter repo cloned, Docker installed.

**New/changed env vars:** None yet — this cycle runs against whatever `.env`/`.env.example` ships with the starter repo, not the expanded `.env.example` in `ARCHITECTURE.md` §23 (that's introduced incrementally starting BC1).

**Workflow:**
1. `docker compose -p assessment up -d --build`.
2. Confirm all four containers report `Up`: `frontend` (Next.js, :3000), `chainlit` (:8000), `backend` (FastAPI, :6100), `relational_db` (Postgres, :5432).
3. Hit each HTTP service's root/health path and confirm a non-error response; confirm a raw `psql`/`asyncpg` connection to Postgres succeeds.
4. Source or construct one test-fixture PDF containing at least one genuine table (not just tabular-looking prose) — this is the fixture BC4's structure-detection tests, BC8's reranker tests, and BC17's end-to-end Playwright smoke test all depend on. Store it under a fixtures path both the backend and frontend test suites can reference.
5. Record the four passing checks (three HTTP/service checks + one DB check) in `local-setup.md` as the canonical "is this environment healthy" reference for every later cycle.

**Architectural decisions & trade-offs invoked:** None new — this cycle validates the starter stack as given, per §0's "keep the starter frameworks" framing; no substitution decision is exercised here.

**Tests to add this cycle:**
- *Other (environment/contract):* a scripted health check (shell script or a trivial `pytest`/`npm` smoke test) asserting all four `local-setup.md` checks pass — this becomes the precondition gate every later cycle's Definition of Done references, so it needs to be re-runnable, not a one-time manual check.

**Definition of done:**
- [ ] `docker compose -p assessment up -d --build` succeeds with no manual intervention.
- [ ] All four containers report `Up`.
- [ ] All four `local-setup.md` checks (3 HTTP/service + 1 DB) pass, and the check script itself is committed.
- [ ] One table-bearing test-fixture PDF exists at a committed, documented path.

**Suggested commit(s):**
- `chore: verify starter stack boots, add local-setup.md health checks`
- `test: add table-bearing fixture PDF for structure-detection and e2e tests`

---

### BC1 — Repo scaffolding + architecture doc committed

**Maps to:** Requirement 6 (local run instructions), bonus (documented architectural decisions); §0, §22.
**Owner:** Backend.

**Objective:** Establish the working-agreement scaffolding this entire project runs on — `ARCHITECTURE.md` itself committed as the source of truth, the three agent skill files committed alongside it, `BUILD_PLAN.md` (this document) committed, and the commit-cadence discipline (§22) actually in effect starting now, not retrofitted later.

**Preconditions:** BC0's Definition of Done is a checked fact — all four containers `Up`, `local-setup.md`'s checks passing, fixture PDF in place.

**New/changed env vars:** None — this cycle is documentation and repo structure, not runtime configuration. The full `.env.example` (§23) is introduced as a *file*, populated incrementally as each later cycle's variables are actually used (see BC3 onward), not dumped in wholesale here.

**Workflow:**
1. Commit `ARCHITECTURE.md` at the repo root as the canonical architecture/decision record.
2. Commit `agents/Backend-engineer-SKILL.md`, `agents/Frontend-engineer-SKILL.md`, `agents/ML-engineer-SKILL.md` — the three build agents' operating specs.
3. Commit `BUILD_PLAN.md` (this document) at the repo root, alongside `ARCHITECTURE.md`.
4. Stub `README.md` with a placeholder structure matching what Requirements 6 and 7 will eventually need (local run instructions, testing instructions, deployment plan) — populated fully at BC19, not written in full now; the stub exists so every later cycle's "update the README" step has somewhere to land incrementally rather than a single monolithic BC19 documentation pass.
5. Confirm `.gitignore` excludes `.env`, `node_modules`, `__pycache__`, and any local storage/upload directories introduced later.
6. Start the commit-cadence discipline (§22) explicitly from this commit forward: `feat:`/`fix:`/`docs:`/`test:`/`chore:` prefixes, frequent commits, no monolithic end-of-assessment commit.

**Architectural decisions & trade-offs invoked:**
- §0/§18: keep the starter frameworks (Next.js + FastAPI), not substitute — restated here as the scaffolding decision this repo structure assumes.
- §22: commit-cadence discipline — named explicitly as a working agreement, not an implicit expectation, because the assessment's own instructions call out "avoid submitting a single, monolithic commit."

**Tests to add this cycle:**
- *Other (repo hygiene):* a CI lint step (even a minimal one — markdown-lint or a basic file-presence check) confirming `ARCHITECTURE.md`, `BUILD_PLAN.md`, and all three `agents/*-SKILL.md` files exist at expected paths — cheap, but it catches an accidental gitignore mistake or a misplaced file early rather than at BC19's documentation review.

**Definition of done:**
- [ ] `ARCHITECTURE.md`, `BUILD_PLAN.md`, and all three `agents/*-SKILL.md` files committed at their documented paths.
- [ ] `README.md` stub committed with placeholder sections for local run, testing, and deployment.
- [ ] `.gitignore` correctly excludes environment/build artifacts.
- [ ] First commit using the `feat:`/`fix:`/`docs:`/`test:`/`chore:` convention is in the repo's history, establishing the pattern for every cycle after.

**Suggested commit(s):**
- `docs: commit ARCHITECTURE.md as the canonical decision record`
- `docs: commit agent skill files and BUILD_PLAN.md`
- `chore: stub README.md structure for later cycles`

---

### BC2 — Database schema + Alembic migration

**Maps to:** Requirement 4 (PostgreSQL + pgvector, tables/indexes not pre-configured); §6, §18.
**Owner:** Backend.

**Objective:** Stand up the full schema from `ARCHITECTURE.md` §6 as a versioned, additive Alembic migration — every table, index, and the one view (`agentops_summary`) the rest of the system will read and write to, even though several tables (`page_images`, `agent_trace_log`, `response_grade`, `anomaly_flag`) won't be populated until much later cycles. Building the whole schema now, rather than table-by-table alongside each feature, keeps foreign keys and `ON DELETE CASCADE` behavior consistent from the start instead of retrofitted.

**Preconditions:** BC1's Definition of Done is a checked fact — `ARCHITECTURE.md` committed as the schema's source of truth, repo scaffolding in place.

**New/changed env vars:**
```bash
# ── Database ─────────────────────────────────────────
DATABASE_URL=postgresql://postgres:postgres@relational_db:5432/ragdb
```
(First entry in the incrementally-built `.env.example`, §23 — the starter repo's own DB connection convention, carried forward unchanged.)

**Workflow:**
1. `CREATE EXTENSION IF NOT EXISTS vector;` and `CREATE EXTENSION IF NOT EXISTS pgcrypto;` (for `gen_random_uuid()`) as the first migration.
2. Create `documents` (`content_hash CHAR(64) UNIQUE` as the dedup key, `status` default `processing`, `metadata JSONB` for the config-version marker used later by §20's scheduling job).
3. Create `chunks`, with `content_tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED` as a **generated column** (§6 revised — no trigger, no app-code write path), `embedding VECTOR(1536)` matching `EMBEDDING_DIM`, the HNSW index (`m=16, ef_construction=64`) and GIN index on `content_tsv`.
4. Create `page_images` (§4.3 addition) — `UNIQUE (document_id, page_number)`, `ON DELETE CASCADE` from `documents`.
5. Create `chat_sessions` and `chat_messages` (`source_chunk_ids UUID[]` for the citation UI, §5.2).
6. Create `exact_cache` and `semantic_cache` (including the `source_doc_ids UUID[]` invalidation-target column on `semantic_cache`, and both HNSW/last-used indexes) — populated starting BC11, schema exists now.
7. Create `query_audit_log`, including `idempotency_key TEXT UNIQUE` (§5.5) and the typed `input_validation_status`/`output_filter_status`/`output_filter_reason` columns (§6 revised — not booleans).
8. Create `agent_trace_log`, `response_grade`, and the `agentops_summary` view (read-time join, no new instrumentation — §6, §11.5).
9. Create `anomaly_flag` (§20.1).
10. Each table above is its **own migration file**, never an edit to a prior migration (§6, §22) — this is what keeps the schema history additive and reviewable.
11. Run the full migration chain against the local `relational_db` container and confirm every table, index, and the view exist as specified.

**Architectural decisions & trade-offs invoked:**
- §18: HNSW over IVFFlat — "no training step; performs better at low-to-moderate row counts, which is this assessment's regime."
- §18: Alembic (versioned, additive) over hand-run `init.sql` — "keeps schema changes in reviewable history, consistent with commit-cadence discipline."
- §6: `content_tsv` as a Postgres generated column rather than application-populated — eliminates an entire class of "forgot to update the tsvector" bugs structurally, at the cost of requiring Postgres 16+ (already the RDS target per §19).

**Tests to add this cycle:**
- *Other (migration):* run `alembic upgrade head` against a fresh database and assert it succeeds with no manual fixups; run `alembic downgrade base` and confirm it cleanly reverses, since a migration that can't downgrade cleanly is a deployment risk flagged early rather than discovered at BC18.
- *Integration:* insert a row into each table via raw SQL/ORM and confirm constraints behave as specified — `documents.content_hash` uniqueness rejects a duplicate, `chunks.content_tsv` populates automatically without being written to, `page_images` `UNIQUE (document_id, page_number)` rejects a duplicate page, `query_audit_log.idempotency_key` uniqueness rejects a duplicate key, cascading deletes from `documents` correctly remove dependent `chunks`/`page_images` rows.

**Definition of done:**
- [ ] Every table and index from §6 exists via Alembic migration, each as its own file.
- [ ] `content_tsv` confirmed to populate automatically on insert with no application code writing to it.
- [ ] `agentops_summary` view created and confirmed to return zero rows cleanly against an empty schema (no join errors).
- [ ] Cascade-delete behavior confirmed for `documents → chunks/page_images`.
- [ ] Migration up/down cycle tested clean.
- [ ] Any implementation choice diverging from §6 (there shouldn't be any at this cycle, but if one emerges) logged in §18 in the same commit.

**Suggested commit(s):**
- `feat: add documents and chunks tables with HNSW/GIN indexes`
- `feat: add page_images, chat_sessions, chat_messages tables`
- `feat: add exact_cache and semantic_cache tables`
- `feat: add query_audit_log, agent_trace_log, response_grade tables and agentops_summary view`
- `feat: add anomaly_flag table`
- `test: add schema constraint and cascade-delete integration tests`

---

### BC3 — PDF upload endpoint + validation limits

**Maps to:** Requirement 2 (dedicated PDF upload page/endpoint — backend half); §4.1, §4.2, §12.3.
**Owner:** Backend.

**Objective:** Build the `/upload` endpoint that accepts a PDF, validates it against §4.1's limits at the API boundary (before any parsing begins), persists a `documents` row with `status=processing`, and returns `202 Accepted` — the ingestion pipeline itself (structure detection, chunking, embedding) is **not** built in this cycle; that starts at BC4. This cycle's scope is strictly upload + validation + the processing-status contract, using local file storage (`UPLOAD_STORAGE_BACKEND=local`), not S3 — cloud storage is a BC18 deployment concern, not a local-dev one (§21).

**Preconditions:** BC2's Definition of Done is a checked fact — `documents` table exists and its constraints (especially `content_hash UNIQUE`) are confirmed working.

**New/changed env vars:**
```bash
# ── PDF Upload Limits ────────────────────────────────
MAX_PDF_SIZE_MB=20
MAX_PDF_PAGES=300
ALLOWED_MIME_TYPES=application/pdf

# ── Storage ────────────────────────────────────────────
UPLOAD_STORAGE_BACKEND=local          # local | s3 — local through BC0–BC17, s3 introduced at BC18
```

**Workflow:**
1. Implement `POST /api/v1/documents` (async FastAPI endpoint, `asyncpg` pool) accepting a multipart file upload.
2. **Validation, in order, before any parsing starts:**
   - File size check against `MAX_PDF_SIZE_MB` — reject `413` if exceeded.
   - MIME/magic-byte check — verify by file header (`application/pdf` magic bytes), **not** the filename extension (§4.1: "an attacker can rename any file `.pdf`; trusting the extension alone is a known bypass") — reject `415` if the header doesn't match.
   - Page count check against `MAX_PDF_PAGES` — this requires a cheap page-count read (e.g., `pdfplumber`'s page count without full parsing); reject `413` if exceeded. Note this check necessarily happens slightly later than size/MIME since it needs the file opened, but still strictly before the ingestion pipeline (structure detection, chunking) begins.
3. On passing validation: compute the SHA-256 `content_hash` (§4.4's dedup key), check it against `documents.content_hash` — if a match exists and its `status = indexed`, short-circuit and return that existing document's status rather than re-processing (dedup, §4.4) — a re-upload of an already-indexed file comes back `indexed` quickly, not reprocessed from scratch.
4. If no existing match: write the uploaded file to local storage (`UPLOAD_STORAGE_BACKEND=local` — a local filesystem path this cycle, S3 at BC18), insert a `documents` row (`status=processing`, `filename`, `content_hash`, `page_count`), and return `202 Accepted` with the new `document_id` and `status: processing`.
5. Implement `GET /api/v1/documents/{document_id}` (status polling) and `GET /api/v1/documents` (list, for the frontend's document list) — both read-only against the `documents` table; no ingestion logic lives here yet, since BC4+ hasn't been built.
6. Implement `DELETE /api/v1/documents/{document_id}` — deletes the `documents` row, relying on `ON DELETE CASCADE` (already confirmed at BC2) to clean up any dependent rows; at this cycle there are none yet, but the endpoint's contract needs to exist for the frontend agent's BC13 delete action to build against.
7. All four endpoints sit behind the JWT auth boundary specified in §12.0 — but full auth implementation is BC15's cycle; for this cycle, stub the auth dependency (e.g., a pass-through or a minimal placeholder check) and flag clearly in code comments and in this document that real auth lands at BC15, so nothing here is mistaken for a finished security posture.

**Architectural decisions & trade-offs invoked:**
- §4.1: upload limits enforced synchronously at the API boundary, before any processing — "fail fast, cheaply, at the edge," bounding worst-case parse time/embedding cost and providing basic DoS defense.
- §4.4: content-hash dedup as the mechanism that makes re-upload idempotent for free, without a separate application-level "does this file already exist" check.
- §4.2: ingestion as a background task, not a blocking request — this cycle establishes the `202 Accepted` / `status=processing` contract that BC4's actual background ingestion work will fulfill; the endpoint doesn't block on parsing because there's no parsing to block on yet at this cycle, but the response shape is built as if there will be, so BC4 doesn't require a breaking API change.

**Tests to add this cycle:**
- *Unit:* MIME/magic-byte validation correctly rejects a renamed non-PDF file (e.g., a `.txt` renamed to `.pdf`) even though the extension passes; oversized file rejected with `413` before any file content is read into memory in full.
- *Integration:* a valid small PDF under all three limits uploads successfully and produces a `documents` row with `status=processing`; a re-upload of the identical file (same `content_hash`) short-circuits rather than creating a duplicate row; `GET /api/v1/documents/{id}` returns the correct status; `DELETE` removes the row.
- *Other (API contract):* schema validation on the multipart request; unauthenticated request to any of the four endpoints is rejected once the BC15 auth dependency is in place (this specific assertion may need to be added retroactively at BC15 if the auth stub in this cycle is a pass-through — note that explicitly in the BC15 cycle write-up when it's expanded).

**Definition of done:**
- [ ] `POST /api/v1/documents` enforces all three §4.1 limits, in the specified order, before any parsing begins.
- [ ] MIME check verifies by file header, not extension.
- [ ] Content-hash dedup confirmed working — a repeat upload of an identical file does not create a second `documents` row.
- [ ] `GET` (single + list) and `DELETE` endpoints implemented and tested.
- [ ] Local storage backend (`UPLOAD_STORAGE_BACKEND=local`) confirmed working; no S3 dependency introduced.
- [ ] `.env.example` updated with this cycle's four new variables, each with the rationale shown above.
- [ ] Auth stub clearly flagged as a placeholder pending BC15, not mistaken for a finished implementation.

**Suggested commit(s):**
- `feat: add POST /api/v1/documents upload endpoint with size/MIME/page-count validation`
- `feat: add content-hash dedup on upload`
- `feat: add document status GET/list and DELETE endpoints`
- `test: add upload validation and dedup integration tests`
- `docs: update .env.example with upload limit variables`

---

## 5. Next Steps

BC4 onward (structure detection through the nightly grading/anomaly-detection job) are scoped in each owning agent's `agents/*-SKILL.md` file at the level of objective + primary `ARCHITECTURE.md` §§ (§8 of `Backend-engineer-SKILL.md` and `ML-engineer-SKILL.md`, §7 of `Frontend-engineer-SKILL.md`). Expand those into this document's full per-cycle template (§3 above) in the next pass, in the same dependency order given in §2's traceability table — BC4/BC5 next, since they're the ML engineer's precondition for everything downstream in retrieval.
