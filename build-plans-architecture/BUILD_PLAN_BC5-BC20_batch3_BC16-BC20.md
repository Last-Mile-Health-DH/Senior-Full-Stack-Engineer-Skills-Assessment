# Build Plan — Continuation (BC16–BC20, Final Batch)

**Picks up exactly where batch 2 (BC11–BC15) leaves off.** BC11–BC15 took the project from a working retrieval/generation pipeline through caching, a real `/chat` endpoint with session and conversation management, the frontend upload page, real guardrails, and auth/rate-limiting. This document specifies **BC16 through BC20** — test consolidation, the frontend/e2e suite, deployment + CI, the README/docs pass, and the nightly retrospective-grading/anomaly-detection job — completing every cycle named in `ARCHITECTURE.md` §22's cadence and its BC0–BC20 traceability table.

All conventions from batch 1 still apply unchanged. This batch closes the last three dangling citations the architecture doc's own revision notes name but never fully resolve in the document body: **§19.1**'s observability table (referenced from the Requirements Traceability Matrix and both revision notes, never actually written as a section), **§20.1**'s anomaly-detection algorithm (a real `anomaly_flag` schema exists, but no prose specifies how a baseline or a flag-trigger condition is computed), and the **four env vars** `ARCHITECTURE.md`'s own §11.6/§20 prose references as living in "§23" but that were never actually added to `.env.example`: `SEMANTIC_CACHE_MAX_ROWS` and `RATE_LIMIT_PER_IP_PER_HOUR` (closed in batches 1–2) and, closed in this batch, `RESPONSE_GRADING_SAMPLE_SIZE` and `ANOMALY_DETECTION_ZSCORE_THRESHOLD`.

---

## BC16 — Backend Tests: Deterministic, Agent-Tool, Then Golden-Set Eval

**Maps to:** §22 cadence item 16 · Requirement 5 · `ARCHITECTURE.md` §11.1, §11.2, §11.5
**Owner:** Backend (test consolidation), ML (golden-set design)

**Objective:** Consolidate the backend test suite across its two build tiers — §11.1's deterministic checks (fast, every CI build) and §11.2's golden-set evaluation (small, sampled, run on demand) — close any gap between what BC1–BC15 each *named* in their own "Tests to add" sections and what actually landed in `tests/`, and build the golden-set runner as a first-class harness that makes §11.5's "full-lineage logging doubles as test infrastructure" claim literally true.

**Preconditions:** BC15 complete — every prior cycle's own test list already exists as scattered files; this cycle's job is consolidation and the golden-set harness specifically, not a rewrite.

**New/changed env vars:** none — this cycle adds a `tests/golden_set/` fixture directory and a `pytest -m golden_set` marker convention, which is test infrastructure, not runtime product config, so it has no `.env.example` entry.

**Workflow:**

1. **Gap audit:** walk every prior cycle's (BC1–BC15) "Tests to add" checklist against the actual `tests/` tree; across 15 real cycles some slippage is realistic — file a short list of anything named but never written, and close each one now. This is a consolidation pass, explicitly not a rewrite of tests that already exist and pass.

2. **§11.1 deterministic tier — confirm complete against the architecture doc's own literal list:** (a) known-fixture ingestion produces expected chunk count/metadata (BC5); (b) a table-page fixture produces a `page_images` row for the correct page, non-table pages skip rasterization (BC4); (c) a synthetic low-text-yield page triggers OCR fallback with non-empty output (BC4); (d) a known query against a known small corpus returns the expected source document (BC7); (e) confidence-gate `expand_query` trigger/non-trigger, asserted via `agent_trace_log` rows specifically, not just the final answer (BC9 — confirm here, don't duplicate); (f) oversized/wrong-MIME upload rejected with the correct status (BC3, BC14); (g) a prompt-injection-shaped query, **including one embedded inside a tool's *output*** — cross-check this is BC14's `sanitize_tool_result` test and isn't silently duplicated as a second, slightly different test; (h) schema validation and unauthenticated-request rejection (BC15).

3. Wire the full deterministic tier into the default `pytest` invocation (matching §11.1's "every CI build"), and **name a concrete speed ceiling — under 60 seconds locally** — since a suite that's merely fast today but has no stated ceiling tends to quietly grow past "every CI build" being a pleasant property into it being a tolerated cost. Anything that would push past the ceiling moves to `-m golden_set` or `-m integration` instead of just being accepted as the new normal.

4. **§11.2 golden-set evaluation, built as a first-class runner:**
   - `tests/golden_set/questions.yaml` — 5–10 hand-written `{question, expected_source_document, expected_answer_contains}` triples: at least one plain-text-only question, at least one table-dependent question against the shared fixture PDF (the same file BC4/BC8/BC17 use — one fixture, not a per-cycle copy), and at least one deliberately ambiguous/multi-part question engineered to exercise the confidence gate.
   - `scripts/run_golden_set.py` (or a `pytest` test tagged `@pytest.mark.golden_set`, run on demand per §11.2, not in default CI): for each question, calls the real `/chat` pipeline end-to-end, then reads the result back through `query_audit_log` + `agent_trace_log` — this is §11.5's claim made literal: the eval report includes `retrieval_mode`, `cache_status`, `grounded`, and the full tool-call trace for every question, not just a pass/fail boolean, because it's built on the same lineage data every other part of the system already writes, not a second data path invented for testing.
   - **Precision@K split by `retrieval_mode`** (§7.6's named validation step): report hit-rate separately for `deterministic` vs. `agentic_expanded` groups — this is literally what would justify or recalibrate `RETRIEVAL_AGENT_CONFIDENCE_THRESHOLD=0.55` (§15.3's own honest caveat, §21 assumption 5). **State explicitly in the report output** — not just implied — that 5–10 questions is not statistically sufficient to responsibly move a production threshold from; the split is built and reported so the *mechanism* for calibration exists, without pretending this assessment-scale golden set is itself sufficient evidence to act on.

5. Output `golden_set_report.md` (regenerated each run, not committed) summarizing hit-rate, grounded-rate, and the retrieval_mode split — this is what BC19's README points a reviewer to as "how to check retrieval quality," rather than a hand-inspected trace someone has to reconstruct manually.

**Architectural decisions & trade-offs invoked (§18):**
- §11.5 — "full-lineage logging doubles as test infrastructure" made literally true: the golden-set runner reads `query_audit_log`/`agent_trace_log` directly rather than re-deriving equivalent information through a parallel harness.
- §7.6/§15.3/§21 assumption 5 — the retrieval_mode split is built and reported, with an explicit statement that this project's golden-set size can't responsibly justify recalibrating the threshold from it alone — a methodological honesty point stated in the tool's own output, not only in architecture prose.
- **New row:** a named 60-second ceiling for the default/deterministic test tier, so "fast, every CI build" stays a property that's checked, not just currently true by accident.

**Tests to add this cycle:**
- *Unit:* `run_golden_set.py`'s report-generation logic correctly buckets results by `retrieval_mode` given a synthetic set of `query_audit_log` rows.
- *Smoke:* the harness runs end-to-end against the BC0 fixture without erroring.
- *Meta:* confirm each of the (h) checks in step 2 above actually has a corresponding, currently-passing test file — the audit's own deliverable.

**Definition of done:**
- [ ] Gap audit complete; every previously-named-but-unwritten test closed.
- [ ] §11.1 deterministic tier complete and running under the default `pytest` invocation, under the 60s ceiling.
- [ ] Golden-set harness built on `query_audit_log`/`agent_trace_log`, not a parallel data path.
- [ ] Report includes the retrieval_mode split with the explicit "not sufficient to recalibrate" caveat in its own output.

**Suggested commit(s):**
- `test: close gap-audit items across BC1-BC15 test suites`
- `test: confirm and finalize §11.1 deterministic tier, enforce speed ceiling`
- `feat: build golden-set runner on query_audit_log/agent_trace_log`
- `feat: add retrieval_mode-split precision@K reporting with calibration-sufficiency caveat`

---

## BC17 — Frontend Tests + E2E Smoke Test

**Maps to:** §22 cadence item 17 · Requirement 5 · `ARCHITECTURE.md` §11.3, §11.4
**Owner:** Frontend (component tests), shared (Playwright e2e)

**Objective:** Consolidate BC13's Jest/RTL component tests, confirm §11.3's claim that "Chainlit's own rendering is exercised indirectly via backend API-contract tests" is actually true rather than assumed, and build the Playwright e2e smoke test §11.3 itself names as **"the single highest-value test in the project"** — the one continuous run spanning ingestion, structure detection, retrieval, the confidence gate, multimodal generation, and citation together.

**Preconditions:** BC16 complete — the golden-set fixture PDF is stable; the e2e test reuses that exact fixture, not a second copy, so the backend and e2e suites can't silently diverge on what "the table page" means.

**New/changed env vars:** `PLAYWRIGHT_BASE_URL` — **deliberately documented in the README's testing section at BC19, not added to `.env.example`.** This is a small, worth-stating scoping decision: `.env.example` is the single source of truth for what the *application* needs to run (§23's own framing); a test-runner's target URL is harness configuration, a different category, and folding it into the same file would blur that boundary rather than clarify it.

**Workflow:**

1. Confirm BC13's Jest/RTL suite (renders, client-side validation, progress/error/empty states) is complete against §11.3's literal list; close any gap the same way BC16 did for the backend tier.

2. **Confirm, don't assume, §11.3's Chainlit-indirect-coverage claim:** identify exactly which BC12 integration tests cover the contract Chainlit's UI actually depends on — streamed-token behavior, the citation payload's shape, the error-message payload's shape. If any of those three was never actually asserted at BC12 (a realistic gap after 12 cycles of a real build), close it as a **BC12 test addition**, not a new, redundant Chainlit-specific frontend test — writing a second test for the same contract from the frontend side would just be two places that can independently go stale.

3. **Build the Playwright e2e smoke test, literally per §11.3's own step sequence:**
   ```
   1. Navigate to /documents.
   2. Upload the shared fixture PDF (the one containing a genuine table).
   3. Poll the *UI* — not the API directly, since this test is exercising BC13's real
      polling UX — until the status badge shows "indexed." Bounded wait (e.g. 60s
      timeout); on timeout, fail loudly with the document's last-observed status in
      the failure message, not a bare "test timed out."
   4. Navigate to the Chainlit chat interface.
   5. Ask a question whose correct answer depends specifically on data inside the
      fixture's table (e.g., a dosage or figure that only appears in tabular form) —
      chosen so a text-only regression (structure detection silently broken, image
      never attached) would fail this test even if the system "answered something."
   6. Assert the response text contains the expected table-derived value.
   7. Assert the response's citation references the specific page number that has a
      page_images row for this document — not merely "cites the right document."
   ```
   Step 7 is the test's real teeth: asserting only the document, not the page, would let flagged-page-only rasterization or citation-page-number wiring silently regress while the test kept passing.

4. Run against a real, test-database-backed backend instance — deliberately an integration-level e2e test, not mocked components. Document the exact local run command (`docker-compose -f docker-compose.test.yml up`, or the project's equivalent) precisely, since an unclear local-run story is the single biggest risk to this test actually getting run rather than quietly skipped by whoever's in a hurry.

5. Wire into CI (BC18) as a separate, slower job from the fast unit/component tiers — it shouldn't block a quick PR round-trip, but it does gate merge to `main` per §19's "tests gate the deploy."

**Architectural decisions & trade-offs invoked (§18):**
- §11.3 — implemented literally, including its own framing of this as the project's single highest-value test.
- **New row:** `PLAYWRIGHT_BASE_URL` lives in the README, not `.env.example` — test-harness config is a different category from app runtime config; conflating the files would weaken `.env.example` as a single source of truth for the latter.
- **New row:** the e2e test asserts the cited *page number*, not just the cited *document* — the stronger assertion is what makes the test actually catch a page-level regression instead of passing vacuously through one.

**Tests to add this cycle:** a deliberate meta-check, run once by hand (not automated): temporarily break table detection (e.g., force `TABLE_DETECTION_METHOD` down a no-op path) and confirm the e2e test actually fails — sanity-checking the assertions aren't tautological before trusting them as a regression gate going forward.

**Definition of done:**
- [ ] Jest/RTL suite complete against §11.3's list; any Chainlit-contract gap closed at BC12, not duplicated here.
- [ ] Playwright e2e test implemented exactly per the seven-step sequence above, including the page-number citation assertion.
- [ ] Local run command documented and confirmed to work from a clean checkout.
- [ ] Meta-check performed: a deliberately broken build fails this test.

**Suggested commit(s):**
- `test: close Jest/RTL gaps against §11.3's component-test list`
- `test: confirm Chainlit-contract coverage in BC12 integration tests, close any gap`
- `feat: implement Playwright e2e smoke test (upload -> index -> table question -> page-cited answer)`
- `chore: document local e2e run command and PLAYWRIGHT_BASE_URL in README`

---

## BC18 — Deployment Config + CI Pipeline (Closes the §19.1 Gap)

**Maps to:** §22 cadence item 18 · Requirement 7 · `ARCHITECTURE.md` §19
**Owner:** Backend/DevOps (shared)

**Objective:** Implement §19's deployment plan for real — Dockerfiles carrying the system-level OCR/rasterization dependencies, the S3 storage backend switched on (staged since BC3/BC9), GitHub Actions CI/CD gating deploy on tests, RDS/Fargate/ALB infrastructure — and close the one dangling citation carried across this entire three-batch series: **§19.1's observability target/alert/owner table**, referenced from the Requirements Traceability Matrix and both of the architecture doc's own revision notes, but never actually written as a section anywhere in the document body.

**Preconditions:** BC17 complete — the full test suite (deterministic, golden-set, component, e2e) exists and passes locally; this is exactly what CI will gate on.

**New/changed env vars:** `UPLOAD_STORAGE_BACKEND=s3` and `PAGE_IMAGE_STORAGE_BACKEND=s3` (already declared with `local` as their dev default; switched on for real here, matching BUILD_PLAN's own "S3 introduced at BC18" note), `S3_BUCKET_NAME`, `AWS_REGION` (already declared, first populated with real deployment values here).

**Workflow:**

1. **Dockerfiles.** Backend: base Python image, `apt-get install -y tesseract-ocr poppler-utils` (§21 assumption 1's Dockerfile line, made real for the first time — not a Python dependency, exactly as the architecture doc calls out), `pip install --no-cache-dir -r requirements.txt`, a non-root runtime user, `HEALTHCHECK` hitting `/health`. Frontend (Next.js) and Chainlit: standard multi-stage Node builds. `docker-compose.yml` (dev, unchanged) plus a production-shaped compose/ECS-task-definition set covering all three app containers plus Postgres/pgvector.

2. **S3 storage backend, switched on for real:** implement the `s3` branch of both `UPLOAD_STORAGE_BACKEND` and `PAGE_IMAGE_STORAGE_BACKEND` (the `local` branch has existed since BC3/BC9) via `boto3`, with a bucket-key convention (`documents/{document_id}/{filename}`, `page_images/{document_id}/{page_number}.png`). **Credentials via IAM role at the ECS task level, not `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` env vars** — the architecture doc names Secrets Manager for API keys specifically (§19); IAM-role-based S3 access is the right-sized equivalent for bucket access and avoids a second, weaker credential path existing alongside it (new Decision Log row, since §23 doesn't spell this distinction out).

3. **CI pipeline (GitHub Actions).** `lint-and-test.yml`, on every PR: backend lint (`ruff`) + `pytest` (deterministic tier only, per BC16's 60s ceiling — golden-set and e2e run on a separate, slower job or on merge to `main` only, matching §11.2's "run on demand" framing); frontend `npm run lint` + `npm test` + the BC17 Playwright suite. `build-and-deploy.yml`, on merge to `main`: build/push the three container images, then deploy (Terraform apply or the platform's native deploy action). **"Tests gate the deploy" implemented literally**, not just documented: `build-and-deploy.yml`'s deploy job declares `needs: [lint-and-test]`.

4. **Infrastructure.** ECS Fargate task definitions for the three containers (§19's own "warm container fits occasionally-long-running requests and a persistent connection pool better than a cold-start function" reasoning, unchanged); RDS PostgreSQL 16+ with `pgvector` enabled (`CREATE EXTENSION IF NOT EXISTS vector;` confirmed present as a migration precondition); Multi-AZ; automated backups/point-in-time recovery; an ALB with health-check-backed target groups per service; Secrets Manager entries for `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/`JWT_SECRET`/`DATABASE_URL`, injected as task-definition environment variables, never baked into an image layer. (If Terraform itself is out of this assessment's practical scope, that's named explicitly here as a documented manual-steps runbook instead — not left ambiguous either way.)

5. **Health-check endpoints:** backend `GET /health` (checks DB pool connectivity, returns `200`/`503`); Next.js and Chainlit's own default health surfaces documented, not rebuilt from scratch.

6. **Close the §19.1 gap — write the observability table, using standard target/alert/owner practice, directly into `ARCHITECTURE.md` §19.1 as part of this cycle's own commit (not deferred to BC19's fold-back pass, since this is new content this cycle produces, not a fold-back of an already-made decision):**

   | Metric | Source | Target | Alert condition | Owner |
   |---|---|---|---|---|
   | p95 request latency | `query_audit_log.latency_ms` | < 3000ms (chat turns), < 500ms (retrieval-only paths) | p95 breaches target for 3 consecutive 5-min windows | Backend on-call |
   | Error rate | ASGI/CloudWatch 5xx count | < 1% of requests | > 2% over a 5-min window | Backend on-call |
   | Cache hit rate | `query_audit_log.cache_status` | > 30% combined (exact + semantic) | sustained < 15% over 1hr | Backend on-call |
   | Groundedness pass-rate | `query_audit_log.grounded`, `response_grade.grounding_check_passed` | > 95% | < 90% over 1hr, or any single-hour drop of > 10 points vs. the same hour the prior day | ML on-call |
   | Output filter rate | `query_audit_log.output_filter_status` | < 5% filtered | > 15% over 1hr | ML on-call |
   | Agentic-expansion rate | `query_audit_log.retrieval_mode` | 10–30% (informational — confirms the gate is neither dead nor always-firing) | > 60% sustained over 1 day (threshold likely mis-set — revisit §7.6) | ML on-call |
   | Cost | `query_audit_log.cost_usd`, `cost_category` | within the deployment's set budget | daily spend > 150% of trailing-7-day average | Backend on-call / eng lead |
   | DB connection pool saturation | `asyncpg` pool metrics | < 80% utilized | > 90% for 5 min | Backend on-call |

**Architectural decisions & trade-offs invoked (§18):**
- §19 — implemented literally: Fargate over serverless, Multi-AZ RDS, S3 for both documents and page images.
- **New row:** S3 credentials via IAM role, not env-var access keys — the right-sized equivalent of the already-named Secrets-Manager pattern, applied specifically to bucket access.
- **New row — closes the §19.1 gap:** the observability table written here with concrete percentile-based targets and sustained-window alert conditions (avoiding single-spike noise) and an explicit owner per metric, so "someone should watch this" is never left unassigned. The architecture doc's own revision notes claimed this was "now covered" without it ever actually being written down; this cycle is where that claim becomes true.
- **New row:** golden-set/e2e tiers run on merge-to-`main` or on demand, not on every PR — extends BC16's speed-ceiling reasoning to the CI pipeline level, keeping the PR feedback loop fast.

**Tests to add this cycle:**
- *CI:* a build step confirming the backend `Dockerfile` builds successfully with `tesseract`/`poppler` present — the exact "pip-only, missing system binary" failure §21 names, now caught at image-build time rather than only documented.
- *Integration:* the `s3` storage-backend branch, tested against a local S3-compatible mock (`moto` or `localstack`), confirming upload/retrieve round-trips correctly for both documents and page images.
- *CI dry-run:* confirm `build-and-deploy.yml`'s deploy job is genuinely gated on `lint-and-test` passing — a missing or broken `needs:` dependency is exactly the kind of silent policy-only gate this test exists to catch.

**Definition of done:**
- [ ] Dockerfiles build with system-level OCR dependencies present, confirmed by a CI check, not just documentation.
- [ ] S3 storage backend implemented for both `documents` and `page_images`, credentialed via IAM role.
- [ ] CI pipeline gates deploy on tests via a real `needs:` dependency, not a documented-only policy.
- [ ] Infrastructure (or a documented manual runbook, if Terraform is out of scope) covers Multi-AZ RDS, backups, health checks, Secrets Manager.
- [ ] §19.1 observability table written into `ARCHITECTURE.md` as a real, numbered subsection.

**Suggested commit(s):**
- `feat: add production Dockerfiles with tesseract/poppler, health checks`
- `feat: implement S3 storage backend for documents and page images (IAM role auth)`
- `feat: add GitHub Actions CI (lint, deterministic tests, golden-set/e2e on merge, deploy gated on tests)`
- `feat: add Terraform/deployment infrastructure (ECS Fargate, RDS Multi-AZ, ALB, Secrets Manager)`
- `docs: write ARCHITECTURE.md §19.1 observability table (closes long-standing dangling citation)`

---

## BC19 — README / Docs Pass

**Maps to:** §22 cadence item 19 · Requirement 6, bonus (documentation) · `ARCHITECTURE.md` §0, all
**Owner:** Shared (Backend-led consolidation, per §0's document map)

**Objective:** Write the real `README.md` (the reviewer's actual entry point, per §0), finalize `local-setup.md`, and fold **every** Decision Log row this three-batch build-plan series has introduced (roughly two dozen, across BC5–BC18) back into `ARCHITECTURE.md` §18 and §19.1 — so the architecture document and the system as actually built describe the same thing, rather than a design that quietly diverged from its own build plan over 19 cycles.

**Preconditions:** BC18 complete — deployment/CI exists, so the README's production-facing section can point at something real.

**New/changed env vars:** none — this cycle documents, it doesn't introduce config. Its own deliverable includes auditing that every var introduced across BC5–BC20 (batches 1–3) is actually present in `.env.example` and actually referenced somewhere in the docs — the inverse of the dangling-citation problem this whole series has been closing.

**Workflow:**

1. **Fold-back pass on `ARCHITECTURE.md` §18 (Decision Log):** append every "new row" this build-plan series flagged across BC5–BC18 — in-memory `PageAssessment` staging; `fetch_page_image`'s no-public-route boundary; the deterministic compaction algorithm; the scheduler-timing split (stood up at BC11, extended at BC20); cache-write eligibility; semantic-cache invalidation's "id no longer resolves" condition; idempotency concurrency handling; the conversation-window/summary trigger; the frontend backend-URL and upload-limits decisions; the grounding-check reuse; `sanitize_tool_result`'s scope; rate-limit-counter reuse via `query_audit_log`; the per-IP ceiling; S3-via-IAM-role; the golden-set/e2e CI-tier split — each landed as a real row in the same table format the architecture doc already uses, not a separate appendix that could itself drift from the canonical table over time.

2. **Confirm §19.1 is genuinely present** as a real, numbered subsection (BC18 wrote it; this cycle confirms it via the cross-link audit in step 6, not by eyeballing).

3. **Finalize `local-setup.md`:** a truly clean-checkout walkthrough — `git clone`, `.env` setup referencing every variable this series adds (including `SEMANTIC_CACHE_MAX_ROWS`, `RATE_LIMIT_PER_IP_PER_HOUR`, and BC20's `RESPONSE_GRADING_SAMPLE_SIZE`/`ANOMALY_DETECTION_ZSCORE_THRESHOLD`/`ANOMALY_DETECTION_BASELINE_LOOKBACK_DAYS`/`GRADING_JOB_CRON`), `docker-compose up`, `alembic upgrade head`, seeding the fixture PDF, and the exact URLs (`:3000`, `:8000`, `:6100`). A troubleshooting section covering the two most likely first-run failures: missing Tesseract/Poppler if running outside Docker, and a missing `ANTHROPIC_API_KEY`/embedding-provider key.

4. **Write `README.md`** as the actual reviewer entry point: what the project is; a link to `ARCHITECTURE.md` §1's requirements-traceability table rather than a duplicate of it (§0's document map explicitly rules out duplication); the exact test-run commands for each tier — deterministic (`pytest`), golden-set (`pytest -m golden_set`), Jest/RTL (`npm test`), Playwright (`npx playwright test`) — finally keeping §11.4's "exact commands named in the README" promise instead of deferring it again; links to `local-setup.md` and `ARCHITECTURE.md`; a short, explicit "what's core-requirement scope vs. bonus scope" summary so a reviewer isn't left reverse-engineering that from the traceability matrix alone.

5. **Docstring drift check:** spot-check every public tool function (`hybrid_search`, `rerank`, `expand_query`, `fetch_page_image`, `compact_chunk`, `chunk_document`, `embed_batch`, `write_chunks`) against its **current** signature and behavior, not the behavior it had when first written — several of these were touched by a later cycle (e.g., `compact_chunk`'s scorer got reused by BC14's grounding check) without necessarily updating the original docstring's framing.

6. **Cross-link audit, run as a small script, not by re-reading 1100+ lines by hand:** grep every `§\d+(\.\d+)?` reference across `BUILD_PLAN*.md`, confirm a matching header actually exists in `ARCHITECTURE.md`. This is a mechanical, repeatable check for exactly the "dangling citation" failure mode this whole document series exists to close (§19.1 and §20.1 were both real instances of it) — closing it with tooling rather than promising to be more careful next time.

**Architectural decisions & trade-offs invoked (§18):**
- §0's document map — enforced literally: no content duplicated between `README.md`/`local-setup.md`/`ARCHITECTURE.md`; each cross-links instead of restating.
- §11.4 — "exact commands named in the README," finally made true.
- **New row:** a scripted cross-reference check as a repeatable substitute for manual re-reading — worth keeping in CI going forward as a lightweight regression gate against future documentation drift (a natural next step past this assessment's own scope, named here, not built as a CI job in this cycle).

**Tests to add this cycle:**
- The cross-link audit script itself, runnable standalone (and a natural CI candidate).
- A companion check that every `.env.example` variable is referenced somewhere in `local-setup.md` or `ARCHITECTURE.md` — the inverse check, catching an undocumented variable rather than a dangling section reference.

**Definition of done:**
- [ ] Every Decision Log row this series names is folded into `ARCHITECTURE.md` §18 in the same table format.
- [ ] §19.1 confirmed present as a real section (cross-link audit passes on it specifically).
- [ ] `local-setup.md` walks a truly clean checkout through to a running system, `.env.example` audited complete.
- [ ] `README.md` states exact, tier-separated test-run commands and links rather than duplicates the other two documents.
- [ ] Cross-link audit script runs clean against the final state of `BUILD_PLAN*.md` and `ARCHITECTURE.md`.

**Suggested commit(s):**
- `docs: fold BC5-BC18 Decision Log rows into ARCHITECTURE.md §18`
- `docs: finalize local-setup.md against a clean-checkout walkthrough`
- `docs: write README.md as the reviewer entry point, tier-separated test commands`
- `docs: docstring drift pass on all public tool functions`
- `chore: add cross-link audit script, confirm zero dangling §N references`

---

## BC20 — Retrospective Response Grading + Anomaly Detection (Nightly)

**Maps to:** bonus (retrospective grading, anomaly detection) · `ARCHITECTURE.md` §6, §11.6, §20, §20.1
**Owner:** Backend + ML (shared)

**Objective:** Extend BC11's scheduler (not build a second one — the Decision Log row batch 2 already logged for exactly this reason) with the nightly job §11.6 names: a deterministic grounding re-check on every prior day's response, sampled LLM-judge rubric scoring, populating `response_grade`. Also **resolve §20.1's anomaly-detection algorithm**, which — like §19.1 before BC18 — has a real target schema (`anomaly_flag`) in `ARCHITECTURE.md` §6 but no prose anywhere specifying how a baseline gets computed or what actually triggers a flagged row. This is the last dangling citation this whole three-batch series inherits from the architecture document itself.

**Preconditions:** BC19 complete — documentation is in sync, so this cycle's own new Decision Log rows land in a clean, non-drifted table rather than one that's already behind.

**New/changed env vars:** `RESPONSE_GRADING_SAMPLE_SIZE=50` (§11.6's own text names this as living in "§23," but it was never actually present in `.env.example` — added here), `GRADING_JOB_CRON=0 2 * * *` (a **separate, new cron variable from BC11's `CACHE_EVICTION_CRON`** — new Decision Log row: §20 describes one "lightweight scheduled job" conceptually, but cache-hygiene (hourly) and grading/anomaly-detection/config-drift (nightly) run on genuinely different cadences that shouldn't share a single cron expression just because they share one scheduler process), **new:** `ANOMALY_DETECTION_ZSCORE_THRESHOLD=3.0` — missing from `.env.example` entirely, added here, **new:** `ANOMALY_DETECTION_BASELINE_LOOKBACK_DAYS=14` — also missing, needed to define "baseline" concretely rather than leaving it implicit.

**Workflow:**

1. **Extend BC11's `AsyncIOScheduler` instance** with two additional jobs — `nightly_grading` and `anomaly_detection` (plus `config_drift_check`, step 5) — on `GRADING_JOB_CRON`. Not a second scheduler process: one piece of infrastructure, jobs added to it across two cycles, exactly as batch 2's Decision Log already commits to.

2. **`nightly_grading` — deterministic re-check, run against every eligible row from the prior day:**
   ```python
   async def nightly_grading_job(db_pool):
       rows = await db_pool.fetch("""
           SELECT id, query, retrieved_chunk_ids
           FROM query_audit_log
           WHERE created_at >= now() - interval '1 day'
             AND id NOT IN (SELECT query_audit_log_id FROM response_grade)
       """)
       for row in rows:
           passed = await rerun_grounding_check(row)   # reuses BC14's grounding-check function directly
           await db_pool.execute(
               """INSERT INTO response_grade
                  (query_audit_log_id, grounding_check_passed, sampled, graded_at)
                  VALUES ($1, $2, false, now())""",
               row["id"], passed,
           )
   ```
   **Reuses BC14's grounding-check function verbatim** (new Decision Log row — the second cycle to reuse it, reinforcing "one grounding algorithm, not a fork" as an ongoing discipline rather than a one-time choice made and then quietly abandoned). The `NOT IN` guard against `response_grade` makes the job safely re-runnable without double-grading.

3. **Sampled LLM-judge scoring** on a fixed `RESPONSE_GRADING_SAMPLE_SIZE` (50) random subset of that day's rows (or all of them, if fewer than 50 exist): a `GENERATION_MODEL_FAST` call — matching §11.6's "the same kind of judgment already used for the golden-set eval" — scored 1–5 against a fixed rubric. **The rubric itself is made concrete here (new Decision Log row, since §11.6 names the mechanism but never states one):** groundedness, relevance, and completeness, each considered, with a single overall 1–5 score plus a short `judge_rationale` explaining the score in one or two sentences. Writes `judge_score`, `judge_rationale`, `sampled=true`.

4. **§20.1 anomaly detection — algorithm resolved here (new Decision Log row; this is the batch's own §19.1-equivalent gap):**
   - For each of the six metrics `anomaly_flag.metric_name` already enumerates (`cost_usd`, `latency_ms`, `cache_hit_rate`, `output_filter_rate`, `grounded_false_rate`, `agentic_expanded_rate`) and each `hour_of_day` bucket (0–23): compute `observed_value` as that metric's aggregate over the just-completed hour, and `baseline_mean`/`baseline_stddev` as the mean/standard deviation of that **same metric, same hour-of-day bucket**, over the trailing `ANOMALY_DETECTION_BASELINE_LOOKBACK_DAYS` (14) days. Hour-of-day bucketing specifically avoids comparing a quiet 3am observation against an all-hours baseline that's dominated by a busy 2pm — exactly the false-positive pattern a naive rolling average would produce on any project with real diurnal traffic.
   - `z_score = (observed_value - baseline_mean) / baseline_stddev`, with an explicit guard: if `baseline_stddev` is `0`, or the bucket has fewer than a minimum sample count (e.g., under 3 prior days of data for that specific hour), **skip flagging for that bucket this run** rather than computing an infinite or meaningless z-score — logged explicitly as an "insufficient baseline data" skip, not silently dropped.
   - **Insert an `anomaly_flag` row only when `|z_score| >= ANOMALY_DETECTION_ZSCORE_THRESHOLD` (3.0)** — the concrete resolution of "what actually triggers a flag," which the schema alone never specified. Every computed z-score is *not* persisted, only ones crossing the threshold — keeps the table a genuine signal rather than a full metrics dump duplicating what `query_audit_log`/CloudWatch already hold.
   - This directly operationalizes §11.6's own closing line — "a sustained drop in `grounding_check_passed` or `judge_score` is exactly the kind of signal §20.1's anomaly detection watches for" — by including `grounded_false_rate` (derived from this same job's own `response_grade` output, step 2, computed just before this step in the same run) as one of the six watched metrics, not as a separate, disconnected system.

5. **`config_drift_check` — the remaining named-but-unbuilt §20 job**, added to the same scheduler on the same `GRADING_JOB_CRON` cadence (a nightly cadence is appropriate for a config-drift check; no fourth cron variable needed): for every `documents` row where `metadata.ingestion_config_version` (first written at BC5) differs from current settings, re-run the appropriate stage — an embedding-only re-run if only `EMBEDDING_MODEL` changed, a full structure-detection/rasterization re-run if `TABLE_DETECTION_METHOD`/`PAGE_IMAGE_DPI` changed — and update the marker on success. This is the first time BC5's config-version marker is actually *read*, six cycles after it was written — confirming that early design choice pays off exactly as intended rather than sitting unused.

**Architectural decisions & trade-offs invoked (§18):**
- §11.6 — implemented literally: deterministic re-check exhaustive (cheap, run on every row), LLM-judge sampled (not exhaustive, matching the architecture doc's own cost reasoning, now backed by a real `RESPONSE_GRADING_SAMPLE_SIZE` default instead of an unset variable).
- **New row:** grounding re-check reuses BC14's function verbatim, not a second implementation.
- **New row:** the judge rubric — groundedness/relevance/completeness, single 1–5 score plus rationale — made concrete where §11.6 names the mechanism but not the rubric.
- **New row — closes the batch's own dangling citation:** §20.1's anomaly-detection algorithm, resolved as hour-of-day-bucketed rolling z-score with an explicit insufficient-data guard and a threshold-gated insert condition — a fully specified, industry-standard (seasonal-baseline z-score) method, closing the last unspecified schema-without-mechanism gap in the whole `ARCHITECTURE.md`/build-plan series.
- **New row:** `GRADING_JOB_CRON` as a variable distinct from `CACHE_EVICTION_CRON` — two genuinely different cadences sharing one scheduler process, not one cron expression.
- §21 assumption 8 — `config_drift_check` is the first real exercise of "config version markers... need to be part of `write_chunks`, not bolted on later" (BC5), confirming that early decision was correctly scoped.

**Tests to add this cycle:**
- *Unit:* z-score computation against synthetic baseline data, including the divide-by-zero and insufficient-sample-count guards.
- *Integration:* a deliberately injected anomalous hour (e.g., a synthetic spike in `output_filter_rate`) produces an `anomaly_flag` row; a normal-variance hour does not.
- *Integration:* `nightly_grading` never double-grades a row already present in `response_grade` (the `NOT IN` guard, re-run twice in the test).
- *Integration:* sampled judge scoring never exceeds `RESPONSE_GRADING_SAMPLE_SIZE` even when more eligible rows exist.
- *Integration:* `config_drift_check` correctly identifies a document whose `metadata.ingestion_config_version.embedding_model` no longer matches current settings and triggers only the embedding re-run for that document (not a full structure-detection re-run), and vice versa for a `TABLE_DETECTION_METHOD` mismatch.

**Definition of done:**
- [ ] `nightly_grading` and `anomaly_detection` jobs added to BC11's existing scheduler, not a second scheduler instance.
- [ ] Deterministic grounding re-check reuses BC14's function; sampled judge scoring respects `RESPONSE_GRADING_SAMPLE_SIZE`.
- [ ] Anomaly detection's baseline computation, guard conditions, and flag-trigger threshold all implemented and independently tested.
- [ ] `config_drift_check` correctly distinguishes embedding-only vs. full re-ingestion triggers.
- [ ] `RESPONSE_GRADING_SAMPLE_SIZE`, `GRADING_JOB_CRON`, `ANOMALY_DETECTION_ZSCORE_THRESHOLD`, `ANOMALY_DETECTION_BASELINE_LOOKBACK_DAYS` all added to `.env.example` with rationale.

**Suggested commit(s):**
- `feat: extend scheduler with nightly_grading job (deterministic re-check + sampled judge scoring)`
- `feat: implement anomaly_detection job (hour-of-day z-score, threshold-gated flag inserts)`
- `feat: implement config_drift_check job (embedding vs. structure-detection re-run triggers)`
- `test: grading idempotency, anomaly z-score, and config-drift-trigger tests`
- `docs: add RESPONSE_GRADING_SAMPLE_SIZE, GRADING_JOB_CRON, ANOMALY_DETECTION_ZSCORE_THRESHOLD, ANOMALY_DETECTION_BASELINE_LOOKBACK_DAYS to .env.example`

---

## Decision Log Rows Added in This Batch (fold into `ARCHITECTURE.md` §18 — this is BC19's own job, listed here for completeness)

| Decision | Choice | Alternative considered | Why |
|---|---|---|---|
| Backend test-suite speed ceiling | 60s for the default/deterministic tier, named explicitly | No stated ceiling | "Fast, every CI build" stays a checked property, not an accident that quietly erodes |
| Golden-set calibration honesty | Report the retrieval_mode split, state explicitly that 5-10 questions can't justify recalibrating the confidence threshold | Silently imply the split is sufficient evidence | Matches §15.3's own honest-caveat framing; avoids overclaiming what a small eval set can support |
| Test-harness vs. app config boundary | `PLAYWRIGHT_BASE_URL` documented in the README, not `.env.example` | Add it to `.env.example` alongside app config | Keeps `.env.example` a single source of truth for what the *application* needs, a different category from test-harness settings |
| E2E citation assertion strength | Assert the specific cited page number, not just the cited document | Assert only "cites the correct document" | The weaker assertion would pass through a page-level citation regression undetected |
| S3 credentials | IAM role at the ECS task level | `AWS_ACCESS_KEY_ID`/`SECRET` env vars | Matches the already-named Secrets-Manager-for-API-keys pattern; avoids a second, weaker credential path |
| §19.1 observability table | Percentile-based targets, sustained-window alert conditions, one named owner per metric | Leave "observability" as a monitoring intent without concrete targets | Closes a citation referenced from the Requirements Traceability Matrix and both revision notes but never actually written |
| CI tiering | Deterministic tests every PR; golden-set/e2e on merge-to-`main` or on demand | Run the full suite, every tier, on every PR | Keeps the PR feedback loop fast, extends BC16's own speed-ceiling reasoning to CI |
| Documentation drift prevention | A scripted cross-link audit over every `§N` reference | Manual re-reading before each release | Repeatable, mechanical, catches exactly the dangling-citation failure mode this series exists to close |
| Nightly grounding re-check implementation | Reuses BC14's grounding-check function verbatim | A second, standalone re-check implementation | Keeps "one grounding algorithm" true across its second real use, not just its first |
| LLM-judge rubric | Groundedness, relevance, completeness → single 1-5 score + short rationale | Leave the rubric unspecified, trust the judge model's own judgment of "quality" | §11.6 names the mechanism but not a rubric; an unstated rubric makes judge scores incomparable over time as prompting drifts |
| §20.1 anomaly-detection algorithm | Hour-of-day-bucketed rolling z-score, 14-day baseline, threshold-gated inserts, explicit insufficient-data skip | Leave "anomaly detection" as an unspecified future capability | The schema (`anomaly_flag`) already existed with no algorithm behind it — the same shape of gap §19.1 had, closed the same way: concretely, with industry-standard method, not left implicit |
| Grading/anomaly job cadence | Separate `GRADING_JOB_CRON` (nightly), distinct from `CACHE_EVICTION_CRON` (hourly) | Reuse one cron expression for all scheduled jobs | The two job families have genuinely different appropriate cadences; sharing a scheduler process doesn't mean sharing a schedule |

---

## This Completes the Build Plan

BC0 through BC20 are now fully specified, at the same executable level of detail throughout: full function signatures, actual SQL, actual algorithms (RRF, sigmoid reranking, extractive compaction, z-score anomaly detection), literal test assertions, and a Definition-of-Done checklist per cycle. Every gap `ARCHITECTURE.md` itself left open — the two genuinely dangling citations (§19.1, §20.1), the four env vars referenced in prose but absent from `.env.example`, the unassigned conversation-management cycle (§8), the unspecified compaction algorithm (§7.4), the unbounded `fetch_page_image` access surface, and the ingestion-to-chunking staging hand-off — has a concrete resolution, logged as a Decision Log row at the cycle that closes it, and folded back into `ARCHITECTURE.md` itself at BC19 rather than left to live only in these build-plan documents.
