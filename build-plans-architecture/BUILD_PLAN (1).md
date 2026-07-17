# BUILD_PLAN.md
### Last Mile Health — Senior Full-Stack Engineer, AI & Digital Health Practice Assessment

## 0. Purpose

This document sequences the build into discrete **Build Cycles (BC)**, each one a small, independently-committable unit of work that maps back to a specific requirement in the project requirements and a specific section of `ARCHITECTURE.md`. It exists so that "commit frequently, with descriptive messages" (§22 of `ARCHITECTURE.md`) has a concrete shape instead of being a vague instruction — every cycle below ends in one or a small number of commits, each traceable to a requirement.

This file does not re-decide anything `ARCHITECTURE.md` has already decided (schema, chunking strategy, agent boundaries, confidence-gate semantics). It sequences the *order* those decisions get built and tested in, and names what "done" means at each step.

---

## 1. Document Map (unchanged from `ARCHITECTURE.md` §0)

- `local-setup.md` — authoritative for "how do I run this locally." BC0 below depends on it existing and its checks passing.
- `ARCHITECTURE.md` — design decisions, schema, trade-offs, deployment plan.
- `README.md` — reviewer's entry point; built out across cycles, finalized at BC19.
- `BUILD_PLAN.md` (this file) — the sequencing and Definition-of-Done contract for every cycle.

---

## 2. Build Cycle → Requirement Traceability (BC0–BC4 excerpt)

| Build Cycle | Assessment Requirement(s) | Primary `ARCHITECTURE.md` §§ |
|---|---|---|
| BC0 | — (pre-req) | `local-setup.md`, §11.3 |
| BC1 | 6, bonus (arch doc) | §0, §22 |
| BC2 | 4 | §6, §18 |
| BC3 | 2 | §4.1, §4.2, §12.3 |
| BC4 | 3, bonus (ML justification) | §4.3, §15.2, §17 |

*(BC5 onward continue the same traceability table in `ARCHITECTURE.md` §22's cadence — chunking/embedding pipeline, Ingestion Agent loop, retrieval, reranking, Retrieval Agent gating, Orchestrator wiring, caching, chat endpoint, frontend upload UX, guardrails, auth/rate-limiting, testing consolidation, deployment, README pass, and the scheduled grading/anomaly job — and are out of scope for this excerpt.)*

---

## 3. How to Read Each Build Cycle

Every cycle follows the same template:
- **Maps to** — the §22 cadence item (if any) and the `ARCHITECTURE.md` §§ it implements.
- **Objective** — one to two sentences.
- **Preconditions** — what must already be true (usually: the previous cycle's Definition of Done).
- **New/changed env vars** — only the incremental set this cycle introduces; the full `.env.example` is §23 of `ARCHITECTURE.md`.
- **Workflow** — the concrete steps, in order.
- **Architectural decisions & trade-offs invoked** — pointers into `ARCHITECTURE.md` §18's Decision Log, summarized in one line each.
- **Tests to add this cycle** — unit, integration, and "other" (contract/migration/security) tests, written *in* this cycle, not deferred.
- **Definition of done** — a checklist; the precondition for the next cycle.
- **Suggested commit(s)** — using §22's `feat:`/`fix:`/`docs:`/`test:`/`chore:` convention.

---

## BC0 — Environment Verification & Test Fixtures

**Maps to:** pre-requisite (not in §22's numbered cadence) · `local-setup.md`, §11.3

**Objective:** Prove the starter stack actually boots, end-to-end, before any application code is written against it — and produce the one test artifact every later cycle depends on: a PDF containing at least one genuine table, used throughout ingestion and retrieval testing (§4.3, §11.3).

**Preconditions:** None — this is cycle zero. Docker and Docker Compose installed locally.

**New/changed env vars:** None introduced yet; `.env` is copied from `.env.example` (§23) as-is, with placeholder secrets, for the sole purpose of getting containers to boot.

**Workflow:**
1. `docker compose -p assessment up -d --build` against the starter compose file (unmodified) — confirm all four containers (Next.js, Chainlit, FastAPI, Postgres) reach `Up`, not `Restarting` or `Exited`.
2. Run `local-setup.md`'s four boot checks (frontend reachable on `:3000`, Chainlit on `:8000`, FastAPI `/docs` on `:6100`, `psql` connects to Postgres on `:5432` and `CREATE EXTENSION vector;` succeeds).
3. **If `local-setup.md` doesn't exist yet or its checks aren't fully specified**, write it now, in this cycle — it is the authoritative "how do I run this" reference per `ARCHITECTURE.md` §0's document map, and BC1's Definition of Done depends on its checks being real and passing, not assumed.
4. Source or construct the fixture PDF: a short (5–10 page) document containing prose, at least one genuine table (not an image of a table — an actual table `pdfplumber.find_tables()` can detect), and, if convenient, one low-text-yield page to double as an OCR-fallback fixture later (BC4). Store it under a `fixtures/` or `tests/fixtures/` directory that ships with the repo, not as an ad hoc local file — every later cycle's ingestion tests reference it by path.
5. Confirm the fixture actually trips the detection heuristic it's meant to test: run `pdfplumber` interactively against it and confirm `find_tables()` returns a non-empty bounding box on the intended page. A fixture that doesn't actually exercise the code path it's named for is worse than no fixture — it gives false test confidence later.

**Architectural decisions & trade-offs invoked:** None yet — this cycle verifies infrastructure, it doesn't make design decisions. If any starter-stack default has to change to get containers booting (a port conflict, a base-image version), log it as the first row added to `ARCHITECTURE.md` §18, even at this early stage, matching the document's own "name it, don't silently omit it" standard.

**Tests to add this cycle:**
- *Other (smoke):* the four `local-setup.md` boot checks themselves, ideally captured as a tiny shell script (`scripts/verify-local.sh`) so this cycle is re-runnable, not just a one-time manual check.
- *Other (fixture validity):* a one-off script or REPL session confirming the fixture PDF's table is detectable — this doesn't need to be a permanent pytest test yet (BC4 will formalize it), but the result should be recorded (e.g., in a comment or short note) so BC4 doesn't have to re-derive it.

**Definition of done:**
- [ ] `docker compose -p assessment up -d --build` succeeds; all four containers report `Up`.
- [ ] All four `local-setup.md` checks pass, and `local-setup.md` itself exists with those checks written down, not just performed ad hoc.
- [ ] Fixture PDF exists in the repo, contains a detectable table, and its path is noted for reuse in BC2–BC4's tests.
- [ ] No application code has been written yet — this cycle is verification only.

**Suggested commit(s):**
- `chore: verify starter stack boots locally, add local-setup.md verification checks`
- `test: add table-bearing fixture PDF for ingestion/structure-detection tests`

---

## BC1 — Repo Scaffolding & Architecture Doc Committed

**Maps to:** §22 cadence item 1 · Requirement 6 (local run instructions, indirectly — this cycle lays the ground for it), bonus (architectural decisions documented) · `ARCHITECTURE.md` §0, §22

**Objective:** Establish the repo structure, tooling, and the living documents (`ARCHITECTURE.md`, `BUILD_PLAN.md`, `README.md` skeleton) that every later cycle reads from and writes back into — so that from BC2 onward, "log it in §18" and "update `.env.example`" are things the repo can actually do, not aspirational.

**Preconditions:** BC0 complete — a booting stack and a validated fixture PDF exist.

**New/changed env vars:** `.env.example` committed in full as specified in `ARCHITECTURE.md` §23 (every variable that section names, even ones later cycles will be the first to actually *use* — committing the full shape now means later cycles only ever add a rationale comment, not restructure the file).

**Workflow:**
1. Establish top-level repo layout separating the three runtime pieces cleanly (`backend/`, `frontend/` (Next.js), `chat/` (Chainlit) — or the equivalent already implied by the starter code's own layout, kept, not reorganized without reason per §18's "substitution policy exists for genuine skill fit, not default" framing).
2. Commit `ARCHITECTURE.md` (already authored) and this `BUILD_PLAN.md` at the repo root, alongside `local-setup.md` (written in BC0) and a `README.md` skeleton that, for now, just points to the other three per §0's document map — it gets filled in properly at BC19, not duplicated early.
3. Commit `.env.example` in full, matching `ARCHITECTURE.md` §23 exactly at this point in time.
4. Set up backend tooling: `pyproject.toml`/`requirements.txt` pinned versions, `pytest` configured with a `tests/` directory and the BC0 fixture reachable from it, linting (`ruff` or equivalent) wired as a pre-commit or CI-ready check even before CI itself exists (BC18).
5. Set up frontend tooling: confirm `npm test` (Jest + RTL, per §11.3) runs green on the starter code's existing (likely trivial) test, so BC13's frontend tests have a working harness to land in later.
6. Add a `.gitignore` appropriate to the stack (Python virtualenvs, `node_modules`, `.env`, local Postgres volumes) — a small thing, but its absence is exactly the kind of "monolithic final commit" smell the project requirements explicitly asks candidates to avoid.

**Architectural decisions & trade-offs invoked:**
- Kept Next.js + FastAPI, no substitution (§18, row 1) — reaffirmed here since this is the cycle where the repo layout locks that decision in structurally, not just on paper.
- `.env.example` as the single source of runtime configuration truth, matching the document's own house style of naming a default and a one-line rationale per variable, rather than letting config drift undocumented across cycles.

**Tests to add this cycle:**
- *Other (tooling):* a passing (even if trivial) `pytest` run and a passing `npm test` run — the point of this cycle is that both harnesses exist and are green, not that they test anything substantive yet.
- *Other (repo hygiene):* confirm `git status` is clean after a fresh clone + install, i.e. nothing untracked-but-required is missing from `.gitignore`'s exclusions.

**Definition of done:**
- [ ] Repo layout finalized and matches (or deliberately, logged, diverges from) the starter code's structure.
- [ ] `ARCHITECTURE.md`, `BUILD_PLAN.md`, `local-setup.md`, and a `README.md` skeleton are all committed and cross-reference each other per §0's document map, without duplicating content across each other.
- [ ] `.env.example` committed in full, matching `ARCHITECTURE.md` §23.
- [ ] `pytest` and `npm test` both runnable and green from a clean clone.
- [ ] `.gitignore` present and correct.

**Suggested commit(s):**
- `docs: commit ARCHITECTURE.md, BUILD_PLAN.md, local-setup.md, README skeleton`
- `chore: scaffold backend (FastAPI) and frontend (Next.js) tooling, pytest + jest harnesses`
- `chore: commit full .env.example per ARCHITECTURE.md §23`

---

## BC2 — Database Schema & Alembic Migration

**Maps to:** §22 cadence item 2 · Requirement 4 (pgvector tables/indexes) · `ARCHITECTURE.md` §6, §18

**Objective:** Stand up the full Postgres + pgvector schema from `ARCHITECTURE.md` §6 as versioned, additive Alembic migrations — including the tables later cycles won't touch until much further along (`agent_trace_log`, `response_grade`), so the schema is complete and reviewable in one place from early in the build, rather than trickling in unannounced alongside whichever feature happens to need a given table.

**Preconditions:** BC1 complete — repo scaffolding and tooling in place; Postgres container from BC0 still boots with the `vector` and `pgcrypto` extensions available.

**New/changed env vars:** `DATABASE_URL` (already in `.env.example` from BC1); `EMBEDDING_DIM=1536` confirmed as the dimension the `chunks.embedding` column is declared with — flagged explicitly here per the Backend skill's own noted gap: this must match whatever `EMBEDDING_MODEL` actually returns, and that check is a real guard to write (§20's embedding-dimension mismatch item), not just a comment, even though the guard's *runtime* enforcement belongs to a later cycle (BC5, at `embed_batch` time) — this cycle only needs the column declared correctly.

**Workflow:**
1. Initialize Alembic against the FastAPI backend's ORM/DB-access layer.
2. Migration 1: extensions (`vector`, `pgcrypto`) + `documents` + `chunks` (with the `content_tsv` **generated column**, not application-populated — per §6's revision, this is declared as `GENERATED ALWAYS AS (to_tsvector('english', content)) STORED` directly in the `CREATE TABLE`, so Postgres keeps it in sync automatically) + the HNSW index (`m=16, ef_construction=64`) + the GIN index on `content_tsv`.
3. Migration 2: `page_images` (§4.3) — its own table, not a column on `chunks`, since multiple chunks can share one page.
4. Migration 3: `chat_sessions` + `chat_messages` (§5.4), including `source_chunk_ids UUID[]` on the latter.
5. Migration 4: `exact_cache` + `semantic_cache` (§9.1/§9.2), including `semantic_cache.source_doc_ids UUID[]` (the eviction-target column) and both the vector-similarity HNSW index and the recency index used by the eviction job later.
6. Migration 5: `query_audit_log` (§6) — with the typed fields kept typed, not collapsed to booleans: `cost_category`, `input_validation_status`, `output_filter_status`, `output_filter_reason`, plus `idempotency_key TEXT UNIQUE` (used starting BC12, declared now so it isn't a schema change later).
7. Migration 6: `agent_trace_log` + `response_grade` + the `agentops_summary` view (§6, §11.5, §11.6) — built now, populated much later (BC10 onward), but declared here so the full schema is reviewable as one coherent unit rather than assembled piecemeal across the whole build.
8. Run every migration up and back down (`alembic upgrade head` / `alembic downgrade base` / `upgrade head` again) to confirm reversibility before calling this cycle done.

**Architectural decisions & trade-offs invoked:**
- HNSW over IVFFlat (§18) — no training step, better recall/speed at this assessment's row-count regime.
- Alembic, versioned and additive, over a hand-run `init.sql` (§18) — keeps schema history reviewable and matches §22's commit-cadence discipline; each table above is its **own migration file**, never an edit to an earlier migration.
- `content_tsv` as a generated column, not a trigger or app-code write path (§6's own revision note) — removes an entire class of "hybrid search silently returns nothing on the lexical half" bug at the source, structurally, rather than relying on application discipline to keep it populated.
- `page_images` normalized as its own table, not a `chunks` column (§4.3) — reflects the real cardinality (many chunks, one page image).

**Tests to add this cycle:**
- *Other (migration):* `alembic upgrade head` then `alembic downgrade base` then `alembic upgrade head` again, asserted in CI-runnable form (even before BC18 wires actual CI) — a broken downgrade path is a real production risk this cycle is exactly positioned to catch early.
- *Integration:* insert a row into `documents`, then a dependent row into `chunks` with a non-trivial `content` string, and assert `content_tsv` is populated **without any application code writing to it** — this is the direct regression test for the bug the revision note calls out.
- *Integration:* insert a `chunks` row with an `embedding` vector of the wrong dimension and confirm Postgres rejects it (pgvector enforces fixed-dimension columns) — a cheap, early version of the dimension-mismatch guard named in §20, at the schema level rather than the application level.
- *Unit:* a small test confirming the HNSW and GIN indexes exist on the expected columns after migration (via `pg_indexes` introspection), so an accidental future migration edit that drops an index doesn't go unnoticed.

**Definition of done:**
- [ ] All tables/view in `ARCHITECTURE.md` §6 exist via versioned Alembic migrations, each table its own migration file.
- [ ] `content_tsv` verified as auto-populating with no app-code write path.
- [ ] Migrations are reversible (`downgrade` tested, not just `upgrade`).
- [ ] `EMBEDDING_DIM` documented and matches the `chunks.embedding` column declaration.
- [ ] Any divergence from `ARCHITECTURE.md` §6 (e.g., a column added or renamed during implementation) logged in §18 in the same commit.

**Suggested commit(s):**
- `feat: add documents, chunks tables with generated content_tsv column, HNSW + GIN indexes`
- `feat: add page_images table`
- `feat: add chat_sessions, chat_messages tables`
- `feat: add exact_cache, semantic_cache tables`
- `feat: add query_audit_log table with typed status/category fields`
- `feat: add agent_trace_log, response_grade tables and agentops_summary view`
- `test: add migration reversibility and content_tsv generated-column tests`

---

## BC3 — PDF Upload Endpoint & Validation Limits

**Maps to:** §22 cadence item 3 · Requirement 2 (PDF upload) · `ARCHITECTURE.md` §4.1, §4.2, §12.3

**Objective:** Build the `/upload` endpoint with every boundary control named in §4.1 enforced *before* any parsing starts, and the background-processing model from §4.2 wired so a large upload never blocks the request path — this cycle intentionally stops short of ingestion logic itself (structure detection is BC4, chunking/embedding is BC5); its job is to get a validated file safely into `documents` with `status=processing` and return control to the client immediately.

**Preconditions:** BC2 complete — `documents` table exists and migrations are applied. Local storage backend only (`UPLOAD_STORAGE_BACKEND=local`) — S3 is explicitly out of scope until BC18 per the Backend skill's own Definition of Done ("no cloud dependency introduced before BC18").

**New/changed env vars:** `MAX_PDF_SIZE_MB=20`, `MAX_PDF_PAGES=300`, `ALLOWED_MIME_TYPES=application/pdf` (all already named in §23; this cycle is the first to actually enforce them), `UPLOAD_STORAGE_BACKEND=local` (confirmed as the active value through BC17).

**Workflow:**
1. Implement `POST /api/v1/documents` accepting a multipart PDF upload.
2. Validation, in order, synchronous, before any processing starts (§4.1):
   - File size ≤ `MAX_PDF_SIZE_MB` — reject `413` if exceeded.
   - MIME/magic-byte check against `application/pdf`, verified by file header (e.g., checking the `%PDF-` magic bytes), **not** the filename extension alone — reject `415` on mismatch. This closes the specific bypass named in §4.1: an attacker renaming an arbitrary file `.pdf`.
   - Page count ≤ `MAX_PDF_PAGES` (a cheap page-count check via the PDF library, without fully parsing content yet) — reject `413`/`422` if exceeded. Note per §4.1: a small file can still have an unreasonable page count (e.g., scanned images), so size and page-count checks are independent, not substitutes for each other.
3. Compute the SHA-256 `content_hash` of the uploaded file and check it against `documents.content_hash` (§4.4's dedup rule) — if a match exists, short-circuit with a clear "already ingested" response rather than creating a duplicate row or re-processing.
4. On passing validation: insert a `documents` row (`status='processing'`), persist the file to local storage under a path keyed by `document_id` (not the original filename, to avoid path-traversal/collision issues), and enqueue ingestion as a background task (`BackgroundTasks`, per §4.2) — **the endpoint returns `202 Accepted` with the `document_id` and `status` immediately**, without waiting on ingestion.
5. Implement `GET /api/v1/documents` (list, for the frontend's status polling — full UX lands at BC13) and `GET /api/v1/documents/{id}` returning `status` — enough for BC13's frontend polling loop to have something real to call, even though this cycle's own scope is backend-only.
6. Enforce input validation (§12.3) as a hook every request passes through before reaching any processing — Pydantic request/response schemas on the endpoint, explicit rejection of malformed multipart bodies, not just relying on FastAPI's default error shape.
7. Leave the actual ingestion body (structure detection, chunking, embedding) as a stub that only flips `status` to `indexed` immediately, for now — BC4 and BC5 replace this stub with the real pipeline. This keeps BC3 scoped to upload + validation, matching its own traceability row.

**Architectural decisions & trade-offs invoked:**
- Fail fast, cheaply, at the edge (§4.1) — all three limits (size, page count, MIME) are enforced synchronously before any parsing, so a malformed or oversized upload costs the system as little as possible.
- Background-task processing model (§4.2, §3 "scalable") — decouples ingestion from the request path; this is what lets the backend scale horizontally with no request-path bottleneck from a slow upload.
- `content_hash` dedup before parsing (§4.4) — invoked here even though full chunking lands in BC5, because the check belongs at the upload boundary, not buried inside the ingestion pipeline.
- Local storage only through BC17 (§18/§19 "no cloud dependency before BC18") — S3 is the named production step, not a build requirement yet.

**Tests to add this cycle:**
- *Unit:* magic-byte validation correctly rejects a renamed non-PDF file even when the extension is `.pdf`.
- *Unit:* size-limit and page-count-limit checks each independently reject files that violate only one of the two constraints (proving they're not substitutes for each other).
- *Integration:* uploading the BC0 fixture PDF returns `202`, creates a `documents` row with `status='processing'`, and the file is retrievable from local storage by `document_id`.
- *Integration:* uploading the same file twice (same `content_hash`) is detected as a duplicate and does not create a second `documents` row or re-trigger processing.
- *Other (contract):* Pydantic schema validation on the upload and status endpoints — malformed multipart bodies and unexpected fields are rejected with a clear `422`, not a raw stack trace.

**Definition of done:**
- [ ] `/upload` enforces size, page-count, and magic-byte checks, in that order, synchronously, before any processing starts.
- [ ] Upload returns `202 Accepted` immediately; ingestion (currently stubbed) runs as a background task.
- [ ] `content_hash` dedup prevents duplicate ingestion of the same file.
- [ ] `GET /documents` and `GET /documents/{id}` exist and return real `status` values from the database.
- [ ] Local storage backend only — no S3/cloud code path introduced yet.
- [ ] Tests above written in this cycle, not deferred.

**Suggested commit(s):**
- `feat: add PDF upload endpoint with size/page-count/magic-byte validation`
- `feat: background-task ingestion stub, document status polling endpoints`
- `feat: content-hash dedup on upload`
- `test: upload validation, dedup, and status-endpoint tests`

---

## BC4 — Structure Detection & Rasterization (Ingestion Agent Tools, Deterministic Layer)

**Maps to:** §22 cadence item 4 · Requirement 3 (RAG backend), bonus (ML/algorithm choices justified) · `ARCHITECTURE.md` §4.3, §15.2, §17

**Objective:** Implement the deterministic tool functions the Ingestion Agent will call starting at BC6 — `detect_structure`, `extract_text_ocr_fallback`, `flag_table_pages` — as plain, directly-callable Python functions first, tested against the BC0 fixture, *before* wrapping them in the agentic loop. This cycle is explicitly about proving the underlying logic is correct; BC6 is where the tool-use loop, iteration cap, and tracing get layered on top of already-working functions, rather than debugging both at once.

**Preconditions:** BC3 complete — a validated PDF can be uploaded and stored. BC2's `page_images` table exists.

**New/changed env vars:** `TABLE_DETECTION_METHOD=pdfplumber`, `PAGE_IMAGE_DPI=200`, `PAGE_IMAGE_STORAGE_BACKEND=local`, `OCR_ENGINE=tesseract`, `OCR_TEXT_YIELD_THRESHOLD=0.15` (all named in §23; this cycle is the first to consume them).

**Workflow:**
1. Implement `detect_structure(document_id, page_number)`: run `pdfplumber`'s `page.find_tables()` for table bounding boxes; compute `text_yield_ratio = extracted_char_count / page_area`; derive `extraction_confidence` (`native_text` vs. `low_yield_needs_ocr`) by comparing that ratio against `OCR_TEXT_YIELD_THRESHOLD`. Returns the shape specified in §15.2: `{has_table, has_figure, table_bbox, text_char_count, text_yield_ratio, heading_candidates, extraction_confidence}`.
2. Implement `extract_text_ocr_fallback(document_id, page_number)`: only called for pages already flagged `low_yield_needs_ocr` by step 1 — never a blanket first pass, since OCR is slower and lower-fidelity than native extraction. Implementation: `pdf2image.convert_from_path` (Poppler-backed) → `pytesseract.image_to_string`. Requires system-level `tesseract-ocr` and `poppler-utils` installed in the Dockerfile (§21, assumption 1) — confirm these are present in the backend container image as part of this cycle, not assumed.
3. Implement `flag_table_pages(document_id, page_numbers)`: rasterize each flagged page via `PyMuPDF` (`page.get_pixmap(dpi=PAGE_IMAGE_DPI)`), store the PNG under `PAGE_IMAGE_STORAGE_BACKEND` (local, through BC17), and upsert a `page_images` row — idempotent, so re-running on an already-flagged page updates rather than duplicates the row.
4. Wire these three functions together as a plain (non-agentic, for now) per-page loop over a document's pages: call `detect_structure`, conditionally call `extract_text_ocr_fallback`, then call `flag_table_pages` for any page with `has_table` or `has_figure` true. This is intentionally *not* the bounded agent loop yet — that wrapping, plus the iteration cap and `agent_trace_log` writes, is BC6's job specifically so structure-detection correctness and agent-loop control-flow aren't debugged simultaneously.
5. Run the full loop against the BC0 fixture PDF end-to-end and confirm: the table-bearing page gets a `page_images` row with `has_table=true`; any low-text-yield page gets routed through OCR and produces non-empty extracted text; pages with neither signal produce no `page_images` row at all (i.e., confirm the heuristic doesn't over-fire).

**Architectural decisions & trade-offs invoked (§17, §18):**
- **No custom ML model for structure detection** — `pdfplumber`'s rule-based `find_tables()` (geometric line/whitespace-grid detection) is chosen over training a classifier, because it's deterministic, already needed for text extraction, and requires no separate model to train or host (§17). Justification, not just a choice: at this corpus scale, a trained detector would add data-labeling and training-infrastructure cost for a signal a mature, already-installed library already provides reliably for the documents in scope (structured protocol/reference PDFs, not adversarially-formatted ones).
- **`PyMuPDF` for rasterization** over alternatives — pure-Python-installable, no extra system binary beyond the wheel itself, fast (§17).
- **Detect-then-rasterize-only-flagged-pages**, never full-page-images-for-every-page (§18 Decision Log) — bounds the later multimodal generation cost (§10) to the pages retrieval actually decides matter, not a blanket approach.
- **Text-yield ratio doubles as both the table/figure corroborating signal and the OCR-fallback trigger** (§4.3) — one signal, two consuming decisions, rather than two separately-tuned heuristics that could disagree with each other.

**Tests to add this cycle:**
- *Unit:* `detect_structure` against the BC0 fixture's table page returns `has_table=true` with a non-empty `table_bbox`; against a plain-prose page returns `has_table=false`.
- *Unit:* a synthetic (or fixture-provided) low-text-yield page produces `extraction_confidence='low_yield_needs_ocr'`, and `extract_text_ocr_fallback` on that page returns non-empty text.
- *Integration:* running the full deterministic loop against the BC0 fixture produces exactly one `page_images` row, on the correct page, with `has_table=true` — and zero `page_images` rows for pages without table/figure signals (i.e., asserting the heuristic doesn't over-fire, not just that it fires at all).
- *Integration:* re-running `flag_table_pages` on an already-flagged page updates the existing row rather than creating a duplicate (idempotency check, direct from §15.2's tool description).
- *Other (environment):* a Dockerfile-level check (or CI step, once BC18 exists) confirming `tesseract` and Poppler binaries are actually present in the backend image — catching the exact "pip-only, missing system binary" failure mode §21 calls out by name before it becomes a deploy-time surprise.

**Definition of done:**
- [ ] `detect_structure`, `extract_text_ocr_fallback`, `flag_table_pages` implemented and independently unit-tested against the BC0 fixture.
- [ ] The BC0 fixture's table page produces exactly the expected `page_images` row; non-table pages produce none.
- [ ] OCR fallback fires only on low-text-yield pages, never as a blanket first pass.
- [ ] System-level OCR/rasterization dependencies confirmed present in the backend container image.
- [ ] These are still plain function calls, not yet wrapped in the agentic tool-use loop — that remains BC6's scope, deliberately.
- [ ] Any divergence in detection thresholds or behavior from §4.3 logged in §18 in the same commit.

**Suggested commit(s):**
- `feat: implement detect_structure (pdfplumber table/figure + text-yield detection)`
- `feat: implement extract_text_ocr_fallback (pytesseract + pdf2image)`
- `feat: implement flag_table_pages (PyMuPDF rasterization, idempotent page_images upsert)`
- `test: structure-detection and rasterization tests against fixture PDF`
- `docs: confirm tesseract/poppler system dependencies in Dockerfile, note in ARCHITECTURE.md §21 if adjusted`

---

## Next cycles (not in this excerpt)

BC5 (chunking + embedding, deterministic tail) through BC20 (scheduled grading job) continue directly from BC4's Definition of Done and follow the same template — see `ARCHITECTURE.md` §22 for the full commit-cadence list this plan is sequenced against.
