# Corrective Build Plan — BC21–BC28

### Last Mile Health — Senior Full-Stack Engineer, AI & Digital Health Practice Assessment

**What this document is.** A *corrective* continuation of the BC0–BC20 build plan. It does not re-open any decision BC0–BC20 made correctly. It patches a set of genuine engineering defects and dangling dependencies found on a close read of `ARCHITECTURE.md` and the three build-plan batches, and it adds the one capability the assessment's own bonus criteria imply but never actually build: a **fixed, versioned, scheduled gold-standard regression evaluation** against a known corpus with known-correct answers, a **weighted marking rubric**, scheduled grading via cron, performance-metric reporting, and deviation alerting.

It is written in the same cycle template as BC0–BC20 (Maps to / Objective / Preconditions / env vars / Workflow / Decisions / Tests / Definition of Done / Commits) so a junior developer can execute it exactly like the cycles before it. Every corrective cycle logs its own Decision Log rows, folded into `ARCHITECTURE.md` §18 at BC28 the same way BC19 folded back BC5–BC18.

Everything not called out here is unchanged from BC0–BC20.

---

## 0. Why these cycles exist — the defect register

Each row is a *specific, reproducible* problem in the current design, not a style preference. The "Severity" column is the author's engineering judgment; "Fixed in" points to the corrective cycle. Items marked **safety** matter more than usual here because the corpus is clinical dosing guidance — a wrong number is not a cosmetic bug.

| # | Defect | Where it lives now | Why it's real | Severity | Fixed in |
|---|---|---|---|---|---|
| D1 | **In-process APScheduler runs on every replica.** §3 says the backend is stateless and scales horizontally (§19); BC11 starts `AsyncIOScheduler` in every FastAPI process's `lifespan`. With N replicas you get N schedulers: `cache_hygiene`, `nightly_grading`, `anomaly_detection`, `config_drift_check` each run N times per tick. The `NOT IN (SELECT ... FROM response_grade)` guard makes grounding re-checks idempotent, but the **sampled LLM-judge call still runs N times** (N× judge cost, N independent random samples) and **anomaly detection inserts duplicate `anomaly_flag` rows**. | BC11 §6, BC20 | Horizontal scaling is an explicit design goal; the scheduler silently breaks it. Cost and data-integrity impact both scale with replica count. | **High** | BC21 |
| D2 | **Token pricing is referenced but never configured.** BC12 step 6 computes `cost_usd` as "the provider's usage response times the configured per-token rate," and `cost_usd`/`cost_category` feed §10, the §19.1 cost alert, and the `anomaly_flag` `cost_usd` metric — but no per-model input/output token rate exists in `Settings` or §23. As written, `cost_usd` can only be `NULL` or hardcoded, silently disabling every cost signal downstream. | BC12, §10, §19.1, BC20 | A load-bearing field three subsystems depend on has no source of truth. | **High** | BC22 |
| D3 | **Rate-limit `COUNT(*)` runs on the hot path with no supporting index.** BC15 counts `query_audit_log` rows filtered by `(session_id, created_at)` and `(client_ip, created_at)` on *every* request, before the cache lookup. `query_audit_log` has only `idempotency_key` indexed (§6), so both counts are sequential scans over a table that grows one row per turn forever. | BC15, §6, §13 | Every request pays an O(table size) scan; latency degrades monotonically with traffic. Directly contradicts §3 "scalable." | Med-High | BC22 |
| D4 | **The primary grounding gate is lexical term-overlap — unsafe for numeric/dosage claims.** BC14's output filter and BC20's nightly re-check both reuse `compact_chunk`'s `|terms(s) ∩ terms(cited)|` scorer with a 0.15 threshold. A hallucinated dose ("give 15 ml amoxicillin") shares vocabulary with the cited chunk and passes; a correct paraphrase using synonyms can fail. For a clinical corpus, a grounding check that is blind to whether the *number* is right is the most consequential weakness in the system. | BC14 §2, BC20 step 2, §7.5, §12.2 | Term overlap cannot distinguish "5 ml" from "15 ml." §16 already frames grounding as defense-in-depth; this makes the second layer real. | **High (safety)** | BC23 |
| D5 | **Semantic cache is not invalidated on embedding-model change.** §9.2 / BC11 invalidate `semantic_cache` only when a referenced `document_id` stops resolving. BC20's re-embedding job can change `EMBEDDING_MODEL`, after which stored `query_embedding` vectors are from a different model (and possibly a different dimension) than incoming query embeddings — cosine similarity becomes meaningless, so near-duplicate lookups silently return wrong hits or none. | §9.2, BC11 §6, BC20 step 5 | The cache's core comparison assumes one embedding space; a config change violates that assumption with no invalidation hook. | Med | BC22 |
| D6 | **`grounded_false_rate` is fed to an hourly z-score detector but produced nightly.** BC20 step 4 buckets every `anomaly_flag` metric by `hour_of_day` over "the just-completed hour," but `grounded_false_rate` derives from `response_grade`, which is written once nightly. There is no hourly signal to bucket; the metric can't work as specified. | BC20 step 4, §20.1 | A named watched metric has no data at the granularity the algorithm reads. | Med | BC24 |
| D7 | **`@cl.step` / `@traced` stacking relies on undocumented no-op-outside-context behavior.** BC12 step 5 stacks `@cl.step` on functions also called directly from pytest, and resolves the conflict by asserting `cl.step` "is a no-op outside a Chainlit context ... confirmed at implementation time." If the installed Chainlit version raises or warns instead, every BC5–BC10 unit test that imports those functions breaks — a fragile dependency on library internals. | BC12 §5, §5.6 | Test-suite integrity hinges on unverified third-party behavior. | Low-Med | BC24 |
| D8 | **LLM-judge scores are not reproducible.** BC20 step 3 scores a sample with `GENERATION_MODEL_FAST` against a rubric, storing only `judge_score` + `judge_rationale`. Model version, temperature, and rubric version are not pinned or stored, so scores drift as the model updates — exactly the "incomparable over time" failure their own Decision Log warns about, only one layer up. | BC20 step 3, §11.6 | Trend detection on a drifting judge measures the judge, not the system. | Med | BC24 |
| D9 | **No fixed, scheduled gold-standard regression eval.** BC16's golden set is 5–10 pairs run *on demand* and explicitly "not sufficient to recalibrate." BC20 grades *live traffic* with no reference answers. Nothing runs a **known corpus + known-correct answers + weighted rubric on a schedule**, reports metrics, and alerts on deviation. The assessment's bonus criteria ("production behavior graded retrospectively," "additional service layers: scheduling") imply this; it is the requested capability. | (gap) | The one standing quality-regression signal the system lacks. | **High** | BC25–BC27 |
| D10 | `content_tsv` hardcodes the `'english'` text-search config; `hnsw.ef_search` `SET LOCAL` must be inside a real transaction; idempotency polling can pin a worker for 10 s. Minor hardening/scaling notes, not blocking. | §6, §7.2, BC12 §1 | Real but low-severity; batched into the hardening cycle. | Low | BC24 |

BC28 is the documentation fold-back (mirrors BC19). BC21–BC24 are the correctness/safety patches; BC25–BC27 build the gold-standard eval, rubric, scheduler, reporting, and alerting — the centrepiece of this corrective plan and the part shipped as ready-to-integrate code in the companion `gold_standard/` package.

---

## BC21 — Scheduler Singleton Guard (fixes D1)

**Maps to:** corrective · `ARCHITECTURE.md` §3, §19, §20, BC11 §6, BC20
**Owner:** Backend/DevOps

**Objective:** Make every scheduled job run **at most once per tick across the whole deployment**, regardless of replica count, without adding infrastructure — closing the horizontal-scaling break D1 describes.

**Preconditions:** BC20 complete — `cache_hygiene`, `nightly_grading`, `anomaly_detection`, `config_drift_check` all exist on the one `AsyncIOScheduler`.

**New/changed env vars:** `SCHEDULER_LEADER_LOCK_KEY=91537` (an arbitrary but fixed 32-bit int, namespacing this app's advisory lock so it can't collide with another app on the same database), added to `.env.example` with that rationale.

**Workflow:**

1. Add a `run_singleton` wrapper in `app/scheduling/singleton.py`. It wraps a job coroutine, takes a **Postgres session-level advisory lock** with `pg_try_advisory_lock`, runs the job only if the lock is acquired, and always releases it in a `finally`:
   ```python
   async def run_singleton(db_pool, lock_id: int, job_name: str, job_coro):
       async with db_pool.acquire() as conn:
           got = await conn.fetchval("SELECT pg_try_advisory_lock($1)", lock_id)
           if not got:
               logger.info("scheduler.skip", job=job_name, reason="not_leader")
               return
           try:
               await job_coro(db_pool)
           finally:
               await conn.execute("SELECT pg_advisory_unlock($1)", lock_id)
   ```
   `pg_try_advisory_lock` is non-blocking: a non-leader replica gets `False` and cleanly skips, so exactly one replica per tick does the work. The lock is held only for the job's duration, released even on exception, and needs no new table or Redis — the same "don't add infrastructure this scale doesn't need" reasoning BC15 already applied to rate limiting.
2. Give each job family its **own** lock id (base `SCHEDULER_LEADER_LOCK_KEY` + a small offset per job) so a long-running `nightly_grading` never blocks `cache_hygiene` on a different replica.
3. Wrap all four existing jobs (BC11's `cache_hygiene`; BC20's `nightly_grading`, `anomaly_detection`, `config_drift_check`) at their registration site. This is the *retrofit* that makes BC11/BC20 correct under scale — the jobs' own bodies are unchanged.

**Architectural decisions & trade-offs invoked (§18):**
- **New row:** scheduled jobs run under a Postgres advisory-lock singleton guard, not a dedicated scheduler process or a leader-election sidecar — right-sized to a single-database deployment, consistent with the Postgres-first posture of §9/§13/§15.
- **New row:** per-job-family lock ids, so job families don't serialize against each other across replicas.

**Tests to add this cycle:**
- *Integration:* two `run_singleton` calls against the same `lock_id` on two pooled connections, launched with `asyncio.gather` — exactly one job body executes; the other logs `not_leader` and returns.
- *Integration:* a job that raises still releases its advisory lock (a follow-up acquisition of the same id succeeds).
- *Unit:* distinct job names map to distinct lock ids.

**Definition of done:**
- [ ] `run_singleton` implemented; all four scheduled jobs wrapped at registration.
- [ ] Concurrent-leader test proves single execution; exception-path test proves lock release.
- [ ] `SCHEDULER_LEADER_LOCK_KEY` in `.env.example` with rationale.

**Suggested commit(s):**
- `fix: run scheduled jobs under Postgres advisory-lock singleton guard (multi-replica safe)`
- `test: scheduler leader-election and lock-release tests`
- `docs: add SCHEDULER_LEADER_LOCK_KEY to .env.example`

---

## BC22 — Cost Pricing Config, Rate-Limit Indexes, Semantic-Cache Model Invalidation (fixes D2, D3, D5)

**Maps to:** corrective · §10, §19.1, §13, §9.2, BC12, BC15, BC20
**Owner:** Backend

**Objective:** Give `cost_usd` a real source of truth; make the hot-path rate-limit counts indexed; invalidate the semantic cache when the embedding model changes. Three small, independent fixes that each close a silent-failure path.

**Preconditions:** BC21 complete.

**New/changed env vars:**
- `MODEL_PRICING_JSON` — a JSON map of model string → `{input_per_mtok, output_per_mtok}` in USD per million tokens, e.g. `{"claude-sonnet-5":{"input_per_mtok":3.0,"output_per_mtok":15.0},"claude-haiku-4-5":{"input_per_mtok":0.8,"output_per_mtok":4.0}}`. Rationale comment: **these are placeholders — verify against current provider pricing at deploy time** (same honesty stance §4.1 takes toward native-PDF thresholds). Prices change; do not trust a hardcoded default.
- No new var for D3/D5 (index + invalidation are code/migration).

**Workflow:**

1. **D2 — pricing:** add `model_pricing: dict` to `Settings`, parsed from `MODEL_PRICING_JSON`. Add `app/core/cost.py::compute_cost(model, input_tokens, output_tokens) -> Decimal`. BC12's finalize step calls it instead of referencing a nonexistent rate. If a model is missing from the map, log a `cost.pricing_missing` warning and write `cost_usd = NULL` **explicitly** (never silently `0.0`, which would read as "free" in the §19.1 cost alert and skew the anomaly baseline).
2. **D3 — indexes:** additive Alembic migration adding two partial indexes matching the exact rate-limit predicates:
   ```sql
   CREATE INDEX CONCURRENTLY qal_session_created_idx
       ON query_audit_log (session_id, created_at DESC);
   CREATE INDEX CONCURRENTLY qal_client_ip_created_idx
       ON query_audit_log (client_ip, created_at DESC)
       WHERE client_ip IS NOT NULL;
   ```
   `CONCURRENTLY` so the migration doesn't lock the table on a live deployment (note in the migration that it must run outside a transaction block). This turns both BC15 counts from sequential scans into index range scans.
3. **D5 — semantic-cache model invalidation:** store the embedding model on each cache row (additive migration: `ALTER TABLE semantic_cache ADD COLUMN embedding_model TEXT;`, backfilled to the current model for existing rows). Two changes: (a) the BC11 semantic lookup query filters `WHERE embedding_model = :current_model`, so a row embedded by a superseded model is never compared against a current-model query embedding; (b) BC20's re-embedding job, when it changes `EMBEDDING_MODEL`, deletes `semantic_cache` rows whose `embedding_model` no longer matches — folded into the same `config_drift_check` job, not a new one.

**Architectural decisions & trade-offs invoked (§18):**
- **New row:** token pricing lives in `MODEL_PRICING_JSON`, explicitly flagged as verify-at-deploy — `cost_usd` is `NULL` (surfaced, alertable) rather than `0.0` (silent) when a model is unpriced.
- **New row:** rate-limit predicates get matching partial indexes, added `CONCURRENTLY`; the hot-path count is no longer O(table).
- **New row:** semantic cache is embedding-model-scoped — a cross-model comparison can never silently return a wrong near-duplicate.

**Tests to add this cycle:**
- *Unit:* `compute_cost` matches a hand-computed value; an unpriced model yields `NULL` + a logged warning, never `0.0`.
- *Other (migration):* `pg_indexes` introspection confirms both rate-limit indexes exist post-migration.
- *Integration:* a `semantic_cache` row written under model A is not returned for a query embedded under model B (invalidation-by-scope), and *is* returned under model A.

**Definition of done:**
- [ ] `cost_usd` computed from real config; unpriced-model path writes `NULL` + warns.
- [ ] Both rate-limit indexes present (migration + introspection test).
- [ ] Semantic cache scoped by `embedding_model`; cross-model lookup returns nothing; drift job deletes stale-model rows.
- [ ] `MODEL_PRICING_JSON` in `.env.example` with the verify-at-deploy caveat.

**Suggested commit(s):**
- `fix: compute cost_usd from MODEL_PRICING_JSON; NULL (not 0.0) on unpriced model`
- `perf: add composite indexes for per-session and per-IP rate-limit counts`
- `fix: scope semantic_cache by embedding_model; invalidate on model change`
- `test: cost computation, rate-limit index presence, semantic-cache model-scope tests`

---

## BC23 — Numeric-Aware Grounding Check (fixes D4 — safety)

**Maps to:** corrective · §7.5, §12.2, §16, BC14, BC20
**Owner:** ML + Backend

**Objective:** Add a grounding signal that actually checks whether the **numbers and dosing units** in an answer are supported by the cited chunks — the single most consequential gap for a clinical-dosing corpus. This does not replace BC14's lexical check; it *adds* a second, cheaper-than-an-LLM, deterministic layer specifically targeting the failure mode term-overlap is blind to (§16's own "second grounding signal, defense-in-depth" framing).

**Preconditions:** BC14 complete (lexical grounding check exists); BC22 complete.

**New/changed env vars:** `GROUNDING_NUMERIC_CHECK_ENABLED=true`; `GROUNDING_NUMERIC_TOLERANCE=0.0` (exact-match by default for dosing — a "close" dose is still a wrong dose; the knob exists so a future non-clinical corpus can loosen it, but it stays 0 here).

**Workflow:**

1. Implement `app/security/numeric_grounding.py::numeric_claims_supported(answer, cited_chunks) -> tuple[bool, list[str]]`:
   - Extract quantity tokens from the answer with a units-aware regex: a number (int/decimal/fraction like `1/2`) optionally followed by a recognized unit (`mg`, `ml`, `kg`, `mg/kg`, `IU`, `mL`, `tablet(s)`, `puff(s)`, `breaths per minute`, `days`, `hours`, `z-score`, `mm`, `°C`, `%`). Normalize fractions (`1/2` → `0.5`) and unit casing.
   - For each extracted `(value, unit)` claim, require that the **same normalized value with a compatible unit** appears in at least one cited chunk's text. A number with a clinical unit in the answer that appears nowhere in the cited sources is an *unsupported numeric claim*.
   - Return `(all_supported, unsupported_claims)`. Bare numbers with no clinical unit (e.g. "step 3", a year like "2014") are ignored — only clinically-meaningful quantities are gated, to avoid false positives on incidental integers.
2. Wire into BC14's output filter as an **additional** check after the lexical grounding check, before send: if `GROUNDING_NUMERIC_CHECK_ENABLED` and there are unsupported clinical numeric claims, set `output_filter_status='filtered'`, `output_filter_reason='numeric_grounding_fail'`, and return the same honest fallback message BC14 already uses (never the raw answer). Add `numeric_grounding_fail` to §6's enumerated `output_filter_reason` values (additive migration/comment only — the column is free-text TEXT).
3. Wire the identical function into BC20's `nightly_grading` deterministic re-check, so the retrospective grade catches the same class of drift on live traffic. Store the unsupported-claim list in `response_grade.judge_rationale` when it's the reason a re-check fails (or a new nullable `grounding_detail JSONB` column if cleaner — additive).
4. This is the check the gold-standard rubric (BC25) also leans on for its safety-weighted numeric-accuracy criterion, so it's implemented once and consumed in three places (pre-send filter, nightly re-check, gold eval) — the same economy-of-effort discipline the architecture applies to `agentops_summary`.

**Architectural decisions & trade-offs invoked (§18):**
- **New row (safety):** a deterministic numeric-grounding check gates clinically-meaningful quantities that appear in the answer but not in any cited chunk — closing the exact failure (wrong dose, right vocabulary) term-overlap cannot see. Chosen over an NLI/entailment model because it's deterministic, dependency-light, and directly targets the dosing failure mode; an entailment model is named as the production upgrade if free-text clinical claims (not just numbers) need checking.
- **New row:** default tolerance is exact-match (0.0) for this corpus — "approximately right" dosing is out of scope for a safety gate.

**Tests to add this cycle:**
- *Unit:* an answer stating "give 5 ml amoxicillin" passes when the cited chunk contains "5 ml"; the same answer stating "15 ml" fails with `15 ml` in the unsupported list.
- *Unit:* fraction normalization — "give 1/2 tablet" is supported by a chunk saying "½ tablet" / "0.5 tablet".
- *Unit:* a bare integer with no clinical unit ("see step 3") never triggers a failure.
- *Integration:* a fabricated-dose answer is filtered pre-send with `output_filter_reason='numeric_grounding_fail'` and the fallback message is returned, not the raw answer.

**Definition of done:**
- [ ] `numeric_claims_supported` implemented, unit-aware, fraction-normalizing, false-positive-guarded on bare integers.
- [ ] Wired into BC14 pre-send filter and BC20 nightly re-check from one implementation.
- [ ] `numeric_grounding_fail` added to the `output_filter_reason` value set.
- [ ] Dosing-specific unit tests (right vs. wrong number) pass.

**Suggested commit(s):**
- `feat: add deterministic numeric/dosage grounding check (safety)`
- `feat: wire numeric grounding into output filter and nightly re-check`
- `test: numeric-grounding right-vs-wrong-dose and fraction-normalization tests`

---

## BC24 — Anomaly-Metric Granularity, Judge Reproducibility, Step Guard, Minor Hardening (fixes D6, D7, D8, D10)

**Maps to:** corrective · §20.1, §11.6, §5.6, §6, §7.2, BC12, BC20
**Owner:** Backend + ML

**Objective:** Fix the grade-derived-metric granularity mismatch, make LLM-judge scores reproducible and comparable over time, remove the fragile `@cl.step` no-op assumption, and clear the minor hardening notes.

**Preconditions:** BC23 complete.

**New/changed env vars:** `JUDGE_MODEL=claude-haiku-4-5`, `JUDGE_TEMPERATURE=0.0`, `JUDGE_RUBRIC_VERSION=1` — pins the judge so scores are comparable across runs (added to `.env.example`). `GROUNDING_TSVECTOR_CONFIG=english` — makes the previously-hardcoded text-search config explicit and swappable for non-English corpora.

**Workflow:**

1. **D6 — grade-derived metric cadence:** split `anomaly_flag` metrics into two families by their natural cadence. Request-derived metrics (`cost_usd`, `latency_ms`, `cache_hit_rate`, `output_filter_rate`, `agentic_expanded_rate`) keep the hour-of-day bucketed hourly z-score BC20 specifies. **Grade-derived metrics** (`grounded_false_rate`, and now `judge_score_mean`) are computed **per nightly grading run** and compared against a **day-of-week-bucketed** rolling baseline over `ANOMALY_DETECTION_BASELINE_LOOKBACK_DAYS`, not an hour-of-day bucket that has no data. Add a `cadence` column (`hourly` | `nightly`) to `anomaly_flag` (additive) so the two families are distinguishable and the §19.1 alert rules can target the right one.
2. **D8 — judge reproducibility:** BC20's judge call uses `JUDGE_MODEL` at `JUDGE_TEMPERATURE=0.0`, and every `response_grade` (and gold-eval) judge row stores `judge_model`, `judge_temperature`, and `judge_rubric_version` alongside the score (additive columns). A score is only comparable to another score with the same triple; the reporting layer (BC27, §19.1) groups trends by that triple and flags a version bump as a **baseline reset**, not a regression.
3. **D7 — step guard:** replace BC12's "trust `cl.step` is a no-op" with an explicit `app/agents/step.py::step(...)` shim that is a real no-op when no Chainlit run context is active (checked via Chainlit's context accessor inside a `try/except`, or an env flag `CHAINLIT_CONTEXT_ACTIVE`), and delegates to `cl.step` only when one is. Pipeline functions decorate with the shim, not `cl.step` directly, so pytest never depends on library-version-specific decorator behavior.
4. **D10 — minor hardening:** (a) `content_tsv`'s generated-column definition reads its config from a documented constant matching `GROUNDING_TSVECTOR_CONFIG` (still `'english'` here, but no longer an unexplained magic literal); note in §6 that a multilingual corpus needs a per-document language column and a different indexing strategy — named, not built. (b) Confirm `hybrid_search` issues `SET LOCAL hnsw.ef_search` inside an explicit `async with conn.transaction():` block (BC7 said "opens its own transaction" — this cycle adds the assertion test that it's a real transaction, since `SET LOCAL` outside one is silently ignored). (c) Cap idempotency polling (BC12) resource cost: the 10 s poll loop yields the connection back to the pool between polls (poll via a fresh short-lived acquire, not a held connection) so a burst of duplicate requests can't exhaust the pool.

**Architectural decisions & trade-offs invoked (§18):**
- **New row:** anomaly metrics are split into hourly (request-derived) and nightly (grade-derived) families with distinct baselines — the grade metrics no longer read a bucket that structurally has no data.
- **New row:** the LLM judge is pinned (`model`, `temperature=0`, `rubric_version`) and every score stores its triple; a rubric-version bump is a baseline reset, not an alert.
- **New row:** `@cl.step` is wrapped in an explicit no-op-outside-context shim, removing the pytest dependency on undocumented library behavior.
- **New row:** `tsvector` config is an explicit constant; idempotency polling no longer holds a pooled connection across the wait.

**Tests to add this cycle:**
- *Unit:* grade-derived metrics use the nightly/day-of-week baseline path; request-derived use the hourly path (dispatch test).
- *Unit:* two judge rows with different `judge_rubric_version` are treated as non-comparable by the trend grouper.
- *Unit:* the step shim is a true no-op (no raise, no side effect) when no Chainlit context is active, exercised directly under pytest.
- *Integration:* `hybrid_search` runs its `SET LOCAL ef_search` inside a transaction (asserted via a connection that would reject `SET LOCAL` outside one).

**Definition of done:**
- [ ] Grade-derived anomaly metrics computed nightly against a day-of-week baseline; `cadence` column present.
- [ ] Judge pinned and its triple stored on every judge score; version bump handled as baseline reset in reporting.
- [ ] `@cl.step` replaced by an explicit shim; pytest no longer depends on library no-op behavior.
- [ ] `tsvector` config explicit; `SET LOCAL ef_search` transaction-scope asserted; idempotency polling pool-safe.

**Suggested commit(s):**
- `fix: split anomaly metrics into hourly and nightly-grade families with correct baselines`
- `fix: pin LLM judge (model/temperature/rubric_version), store triple per score`
- `fix: replace @cl.step trust-the-noop with an explicit context-guarded step shim`
- `chore: explicit tsvector config, assert ef_search transaction scope, pool-safe idempotency polling`

---

## BC25 — Gold-Standard Corpus + Weighted Question Bank + Rubric (fixes D9, part 1)

**Maps to:** corrective, bonus (retrospective grading, ML justification) · §11.2, §11.6, §7.6
**Owner:** ML (question/rubric design), Backend (corpus tooling)

**Objective:** Stand up a **fixed, versioned gold-standard corpus** (three real WHO/UNICEF community-health protocol PDFs), a **weighted question bank** of known-correct Q&A with expected source document + page + facts, and a **weighted marking rubric** — the reference artifacts the scheduled eval (BC26) grades against. This is what BC16's on-demand 5–10-pair golden set is not: fixed, corpus-pinned, weighted, and built to run unattended on a schedule.

All of BC25–BC27's deliverables ship as ready-to-integrate code in the companion **`gold_standard/`** package (see its `README.md`); this cycle specifies what they must contain and why.

**Preconditions:** BC24 complete. A generation model confirmed multimodal (§21 assumption 2) so table-page questions exercise the page-image path.

**New/changed env vars:** `GOLD_CORPUS_DIR=./gold_standard/corpus/files`, `GOLD_QUESTIONS_PATH=./gold_standard/questions.yaml`, `GOLD_RUBRIC_PATH=./gold_standard/rubric.yaml` (added to `.env.example`).

**Workflow:**

1. **Corpus (three documents, all authoritative, freely downloadable, table/chart-rich — chosen to stress structure detection and page-image retrieval, and to yield unambiguous numeric answers):**
   - **WHO IMCI Chart Booklet (2014)** — first-level facility health worker; dosage tables, colour-coded classification charts, decision trees.
   - **WHO Pocket Book of Hospital Care for Children, 2nd ed (2013)** — referral/inpatient; ETAT triage, dense dosing tables.
   - **WHO/UNICEF Caring for the Sick Child in the Community (2011)** — community health worker level (Last Mile Health's actual deployment context); danger-sign and CHW-treatment tables.

   These are pinned by URL + expected filename + **trust-on-first-use SHA-256** in `corpus/corpus_manifest.yaml`; `corpus/fetch_corpus.py` downloads, checksums, and pins them so grading is reproducible even if a source reissues a file. The corpus spans community → outpatient → referral tiers — the exact shape of protocol set an LMH RAG deployment serves.
2. **Question bank (`questions.yaml`)** — 20+ entries, each with: `id`, `question`, `source_doc`, `expected_page` (or page range), `expected_answer` (canonical text), `expected_facts` (the atomic facts that must be present — e.g. the dose value + unit + frequency + duration + age/weight band), `weight` (question importance; **safety-critical dosing questions weighted highest**), and `category` (`dosing`, `threshold`, `classification`, `procedure`, `refusal`). Include **negative/refusal questions** whose correct answer is "not in these documents / refer" — these test that the system declines to fabricate, which for a clinical corpus is as important as answering correctly. **Every expected answer is marked `verified: true|false`**; a maintainer runs the one-time verification pass (step 4) before any score is trusted.
3. **Weighted marking rubric (`rubric.yaml`)** — per-answer criteria, each 0–1, combined by weight into a 0–100 per-question score:
   - **Numeric/factual accuracy** (weight 0.45, highest) — are the required `expected_facts` numbers/units present and correct? Reuses BC23's `numeric_claims_supported` against the *source* to verify no fabricated numbers, and checks the *expected* facts are present.
   - **Grounding / citation correctness** (0.25) — does the answer cite the correct `source_doc` and `expected_page`?
   - **Completeness** (0.20) — are the qualifying conditions present (age/weight band, frequency, duration)?
   - **Safety / refusal correctness** (0.10) — for refusal questions, did it correctly decline/refer instead of answering; for answer questions, no dangerous fabrication.

   Per-question score = Σ(criterion_score × criterion_weight) × 100. Corpus score = weighted mean of per-question scores using each question's `weight`. Category scores = weighted mean within category, so a dosing-accuracy regression is visible even if the overall score holds.
4. **One-time verification pass** — `gold_standard/verify_expected.py`: for each question, prints the `expected_answer` + `expected_page` and the extracted source text at that page, for a human (a clinician or the maintainer) to confirm before flipping `verified: true`. The gold eval **refuses to score against unverified questions** (they're reported as `skipped: unverified`), so a wrong expected answer can never silently drive a false regression alert. This mirrors the architecture's own "starting default, not derived from data — name the calibration step" honesty.

**Architectural decisions & trade-offs invoked (§18):**
- **New row:** the gold corpus is three real, tier-spanning WHO/UNICEF protocol PDFs, pinned by trust-on-first-use checksum for reproducibility — not synthetic fixtures, because the point is to measure behavior on the document *shape* production actually serves.
- **New row:** the rubric is explicitly weighted toward numeric/dosing accuracy and includes refusal questions — a clinical eval that only rewards answering, never correct declining, measures the wrong thing.
- **New row:** unverified expected answers are `skipped`, never scored — a gold standard whose ground truth isn't confirmed can manufacture false regressions.

**Tests to add this cycle:**
- *Unit:* rubric scoring math — a hand-constructed answer with known criterion scores produces the exact expected weighted per-question and corpus score.
- *Unit:* a refusal question is scored correctly when the system declines, and scored 0 on safety when it fabricates an answer.
- *Smoke:* `fetch_corpus.py` downloads all three PDFs, checksums match the pinned (or first-use-pinned) values, and each is a valid PDF.
- *Meta:* the eval refuses to score an `verified: false` question (reports it `skipped: unverified`).

**Definition of done:**
- [ ] `corpus_manifest.yaml` + `fetch_corpus.py` fetch and pin all three PDFs reproducibly.
- [ ] `questions.yaml` has 20+ weighted, categorized questions incl. refusal cases, each with expected facts/page and a `verified` flag.
- [ ] `rubric.yaml` defines the four weighted criteria and the roll-up math; scoring math unit-tested.
- [ ] `verify_expected.py` exists; unverified questions are skipped, never scored.

**Suggested commit(s):**
- `feat: add gold-standard corpus manifest and reproducible fetch/checksum tooling`
- `feat: add weighted gold question bank (incl. refusal cases) and marking rubric`
- `feat: add one-time expected-answer verification pass; skip unverified questions`
- `test: rubric scoring math, refusal scoring, corpus fetch/checksum tests`

---

## BC26 — Gold-Standard Runner + Grader (fixes D9, part 2)

**Maps to:** corrective, bonus · §11.2, §11.5, §11.6
**Owner:** ML + Backend

**Objective:** Build the runner that executes every verified gold question through the **real `/chat` pipeline**, grades each answer against the BC25 rubric (deterministic checks + a pinned LLM judge for the qualitative criteria), and persists a full, reproducible run record — reading lineage back through `query_audit_log`/`agent_trace_log` exactly as §11.5 intends, so the gold eval sits on the same data path as everything else rather than inventing a parallel one.

**Preconditions:** BC25 complete (corpus, questions, rubric). A running backend the runner can call.

**New/changed env vars:** `GOLD_EVAL_JUDGE_MODEL` (defaults to `JUDGE_MODEL` from BC24), `GOLD_EVAL_CONCURRENCY=2` (bounded parallelism so a gold run doesn't spike load), added to `.env.example`.

**Workflow:**

1. **Schema (additive Alembic migration):**
   - `gold_eval_run` — one row per run: `id`, `run_at`, `git_sha`, `corpus_version`, `rubric_version`, `judge_model`, `judge_temperature`, `overall_score`, `question_count`, `skipped_count`, `trigger` (`scheduled` | `manual` | `ci`).
   - `gold_eval_result` — one row per question per run: `run_id` FK, `question_id`, `category`, `weight`, `per_question_score`, `criterion_scores JSONB`, `passed`, `answer_text`, `cited_docs`, `cited_pages`, `query_audit_log_id` FK (the lineage link), `judge_rationale`.
   - Both under the singleton-guarded scheduler's write path (BC21).
2. **Runner (`gold_standard/runner.py`)** — for each `verified` question, at `GOLD_EVAL_CONCURRENCY`: call the real `/chat` endpoint through the thin `client.py` adapter (the one integration point the novice binds to their deployment), capture the answer + the `query_audit_log_id` for lineage, then grade.
3. **Grader (`gold_standard/grader.py`)** — applies the rubric:
   - *Numeric/factual accuracy* and *grounding/citation* are **deterministic** (BC23's numeric check + `expected_facts` presence + cited-doc/page match) — cheap, reproducible, no model call.
   - *Completeness* and *safety/refusal* use the **pinned judge** (`JUDGE_MODEL`, temp 0, `JUDGE_RUBRIC_VERSION`) with a fixed prompt that scores only those two criteria against the `expected_answer`. Storing the judge triple (BC24) keeps scores comparable across runs.
   - Combine into per-question and corpus/category scores per BC25's math.
4. **Report artifact** — `runner.py` writes `gold_eval_report.md` (regenerated each run, not committed): overall score, per-category scores, per-question pass/fail with criterion breakdown and lineage links, and the skipped-unverified list. This is what BC28's README points a reviewer to for "is retrieval quality holding," the standing analogue of BC16's on-demand golden-set report.
5. **CI hook (optional, off by default):** the runner is runnable as `python -m gold_standard.runner --trigger ci` so a team can gate merge-to-`main` on the corpus score not dropping below a floor — extends BC18's "tests gate the deploy," but off by default because it makes real model calls (cost).

**Architectural decisions & trade-offs invoked (§18):**
- **New row:** the gold runner calls the real `/chat` and reads back `query_audit_log`/`agent_trace_log` — the eval is on the same lineage path as production, not a parallel harness (§11.5 made literal, a second time).
- **New row:** deterministic criteria (numeric, grounding) are graded without a model call; only the two qualitative criteria use the pinned judge — keeps a full gold run cheap and its two most safety-relevant criteria fully reproducible.

**Tests to add this cycle:**
- *Unit:* the grader produces the exact rubric score for a synthetic answer with known criterion outcomes.
- *Integration:* a full runner pass against a 2-question mini-set (mocked `/chat`) writes one `gold_eval_run` and two `gold_eval_result` rows with lineage FKs populated.
- *Integration:* the run is safely re-runnable — a second run inserts a new `run` row, never mutates a prior one.

**Definition of done:**
- [ ] `gold_eval_run` / `gold_eval_result` migrations applied; both writes singleton-guarded.
- [ ] Runner executes verified questions through real `/chat`, captures lineage, grades via rubric.
- [ ] Deterministic criteria need no model call; qualitative criteria use the pinned judge with its triple stored.
- [ ] `gold_eval_report.md` regenerated each run; skipped-unverified questions listed.

**Suggested commit(s):**
- `feat: add gold_eval_run/gold_eval_result schema (lineage-linked)`
- `feat: implement gold-standard runner against real /chat with bounded concurrency`
- `feat: implement rubric grader (deterministic numeric+grounding, pinned-judge qualitative)`
- `test: grader scoring, full-run persistence, and re-run-safety tests`

---

## BC27 — Scheduled Grading, Metrics Reporting, Deviation Alerts (fixes D9, part 3)

**Maps to:** corrective, bonus (scheduling, retrospective grading, observability) · §19.1, §20, §20.1, §11.6
**Owner:** Backend + ML

**Objective:** Run the gold eval **on a schedule** (cron), report performance metrics, and **raise deviation alerts** when scores drop against a rolling baseline — closing the last part of D9 and delivering the exact requested capability: *"sampled responses graded on schedule against the marking-rubric gold standard, reporting performance metrics and creating deviation alerts."*

**Preconditions:** BC26 complete (runner + grader persist runs). BC21's singleton guard exists.

**New/changed env vars:** `GOLD_EVAL_CRON=0 3 * * *` (nightly at 03:00, a **third** cadence distinct from `CACHE_EVICTION_CRON` hourly and `GRADING_JOB_CRON` at 02:00 — the gold run reads the prior grading run's outputs, so it runs after it); `GOLD_EVAL_BASELINE_LOOKBACK_RUNS=14`; `GOLD_EVAL_DEVIATION_ABS_DROP=5.0` (alert on ≥5-point absolute drop vs. baseline mean); `GOLD_EVAL_DEVIATION_ZSCORE=3.0` (alert on |z|≥3 vs. baseline distribution) — all added to `.env.example` with rationale. `GOLD_EVAL_SAMPLE_SIZE` (optional) to run a weighted random subset per scheduled tick instead of the full bank, for cost control on large banks; unset = run all.

**Workflow:**

1. **Scheduled job (`gold_standard/scheduler_job.py`)** — register `gold_eval_job` on the existing `AsyncIOScheduler` (BC11), on `GOLD_EVAL_CRON`, wrapped in BC21's `run_singleton` (its own lock id). Not a second scheduler. If `GOLD_EVAL_SAMPLE_SIZE` is set, it grades a **weight-proportional random sample** (so high-weight dosing questions are over-represented, matching what the deviation alert most needs to catch); unset runs the full bank.
2. **Baseline** — the mean and stddev of `gold_eval_run.overall_score` (and each category score) over the trailing `GOLD_EVAL_BASELINE_LOOKBACK_RUNS` completed runs, **excluding runs whose `rubric_version` differs from the current one** (a rubric change is a baseline reset — BC24's principle applied to the gold eval). Fewer than 3 prior comparable runs → skip alerting this tick, log `insufficient_baseline`, exactly as BC20's anomaly detection guards its own cold start.
3. **Deviation alerts (`gold_standard/reporting.py`)** — after a scheduled run, for the overall score and each category:
   - Absolute-drop alert: `baseline_mean − observed ≥ GOLD_EVAL_DEVIATION_ABS_DROP`.
   - Z-score alert: `(observed − baseline_mean)/baseline_stddev ≤ −GOLD_EVAL_DEVIATION_ZSCORE`.
   - Either condition writes an `anomaly_flag` row (`metric_name='gold_eval_overall'` or `gold_eval_<category>'`, `cadence='nightly'`, the observed/baseline/z fields BC20's schema already has) **and** emits a structured `gold_eval.deviation` log event carrying the run id, the offending category, the top regressed questions (largest per-question score drops vs. their own trailing mean), and the report path. Routing that log event to email/Slack/PagerDuty is a deployment concern (one function, `emit_alert`, with a documented webhook TODO) — the *detection* is built here; the *transport* is a config binding, consistent with how §19.1 assigns owners without hardcoding a pager.
   - **A per-category alert fires even when overall holds** — a dosing-accuracy regression masked by steady classification/procedure scores is exactly the signal this exists to catch, which a single overall number would hide.
4. **§19.1 integration** — add gold-eval rows to the observability table so the new signal has a target/alert/owner like every other metric:

   | Metric | Source | Target | Alert condition | Owner |
   |---|---|---|---|---|
   | Gold-eval overall score | `gold_eval_run.overall_score` | ≥ 90 | ≥5-pt drop vs. 14-run baseline, or z ≤ −3 | ML on-call |
   | Gold-eval dosing-category score | `gold_eval_result` (category=`dosing`) | ≥ 95 (safety-weighted) | any drop ≥ 3 vs. baseline | ML on-call |
   | Gold-eval refusal-category score | `gold_eval_result` (category=`refusal`) | ≥ 95 | any single-run drop (fabrication regression) | ML on-call |

5. **README pointer** — BC28 documents the exact commands: one-time `fetch_corpus.py` + `verify_expected.py`, manual `python -m gold_standard.runner`, and how the scheduled job is enabled (`ENABLE_SCHEDULED_JOBS=true` + `GOLD_EVAL_CRON`), plus a **standalone `crontab.example` / systemd-timer** alternative for teams that would rather trigger `runner.py` from OS cron than the in-process scheduler.

**Architectural decisions & trade-offs invoked (§18):**
- **New row:** the gold eval runs on its own nightly cron after the grading job, on the shared singleton-guarded scheduler — a third distinct cadence, not a reused expression, matching BC20's own "different cadences don't share one cron" reasoning.
- **New row:** deviation alerting is dual (absolute-drop OR z-score), per-category as well as overall, with a rubric-version-aware baseline reset — a dosing regression can't hide behind a steady overall mean.
- **New row:** alert *detection* is built; alert *transport* (email/Slack/webhook) is a documented one-function binding — the same target/alert/owner-without-hardcoded-pager stance §19.1 takes.

**Tests to add this cycle:**
- *Unit:* deviation logic fires on a ≥5-pt absolute drop and on z ≤ −3, and does not fire on normal variance; a rubric-version mismatch triggers baseline reset (no alert), not a false regression.
- *Unit:* `insufficient_baseline` skip when fewer than 3 comparable prior runs.
- *Integration:* a synthetic run with a deliberately tanked dosing category writes a `gold_eval_dosing` `anomaly_flag` even when the overall score is within tolerance.
- *Integration:* the job is singleton-guarded (only one replica runs it — reuses BC21's harness).

**Definition of done:**
- [ ] `gold_eval_job` on `GOLD_EVAL_CRON`, singleton-guarded, optional weighted sampling.
- [ ] Baseline is rubric-version-scoped with a cold-start guard; overall + per-category deviation alerts implemented (dual condition).
- [ ] Alerts write `anomaly_flag` + emit a structured event; transport is a documented `emit_alert` binding.
- [ ] §19.1 gains gold-eval overall/dosing/refusal rows with target/alert/owner.
- [ ] All new env vars in `.env.example`; `crontab.example`/systemd-timer alternative documented.

**Suggested commit(s):**
- `feat: schedule gold-standard eval on its own nightly cron (singleton-guarded)`
- `feat: rubric-version-aware baseline + dual (abs-drop/z-score) per-category deviation alerts`
- `feat: write anomaly_flag + structured deviation event; document emit_alert transport binding`
- `docs: add gold-eval rows to §19.1; add crontab/systemd-timer alternative`
- `test: deviation-alert firing, baseline-reset, cold-start, and singleton-guard tests`

---

## BC28 — Corrective Docs Fold-Back

**Maps to:** corrective · §18, §19.1, §0, all
**Owner:** Shared (Backend-led)

**Objective:** Fold every Decision Log row BC21–BC27 introduced into `ARCHITECTURE.md` §18 and §19.1, update `.env.example` and `local-setup.md` for every new variable, extend the BC19 cross-link audit to cover this document, and add the gold-eval commands to the README — so the architecture doc and the system as actually built still describe the same thing after the corrective pass, exactly as BC19 did for BC5–BC18.

**Preconditions:** BC27 complete.

**Workflow:**

1. Append BC21–BC27's Decision Log rows (below) to `ARCHITECTURE.md` §18 in the same table format.
2. Confirm §19.1 now carries the gold-eval rows (BC27 wrote them) via the BC19 cross-link/`.env`-audit scripts, extended to include `CORRECTIVE_BUILD_PLAN_BC21-BC28.md` in their scan set.
3. Update `.env.example` with every BC21–BC27 variable, each with its one-line rationale (the same house style), and confirm the inverse audit: every new var is referenced somewhere in the docs.
4. Add to `README.md`: the gold-standard eval quickstart (fetch → verify → run → schedule), pointing at `gold_standard/README.md` rather than duplicating it (§0's no-duplication rule).

**Definition of done:**
- [ ] All BC21–BC27 Decision Log rows in `ARCHITECTURE.md` §18.
- [ ] §19.1 gold-eval rows confirmed present via the audit script.
- [ ] `.env.example` complete for BC21–BC27; inverse audit passes.
- [ ] README points to the gold-standard package without duplicating it; cross-link audit clean over the corrective plan.

**Suggested commit(s):**
- `docs: fold BC21-BC27 Decision Log rows into ARCHITECTURE.md §18/§19.1`
- `docs: complete .env.example and local-setup.md for corrective cycles`
- `docs: add gold-standard eval quickstart to README, extend cross-link audit`

---

## Decision Log Rows Added by This Corrective Plan (fold into `ARCHITECTURE.md` §18 at BC28)

| Decision | Choice | Alternative considered | Why |
|---|---|---|---|
| Scheduler concurrency under horizontal scaling | Postgres advisory-lock singleton guard per job family | Dedicated scheduler process; leader-election sidecar; Redis lock | Right-sized to a single-DB deployment; no new infra; fixes N-replica duplication without changing job bodies |
| `cost_usd` source of truth | `MODEL_PRICING_JSON`, `NULL` (not `0.0`) when a model is unpriced | Hardcode rates; leave `cost_usd` NULL | A load-bearing field for §10/§19.1/anomaly detection needs a real, verify-at-deploy source; silent `0.0` corrupts cost signals |
| Rate-limit count performance | Composite partial indexes on `(session_id, created_at)` and `(client_ip, created_at)` | Leave unindexed; move counters to Redis | Turns an O(table) hot-path scan into an index range scan while keeping the Postgres-first posture |
| Semantic-cache correctness across model change | Scope cache rows by `embedding_model`; invalidate on change | Compare across models and hope; rebuild the whole cache | Cosine similarity across two embedding spaces is meaningless; scoping is the minimal correct fix |
| Clinical grounding | Deterministic numeric/dosage grounding check as a second layer | Term-overlap only; NLI/entailment model | Term overlap can't tell 5 ml from 15 ml; a numeric check targets the exact safety failure without a model dependency |
| Anomaly-metric granularity | Split hourly (request-derived) vs. nightly (grade-derived) baselines | One hour-of-day baseline for all metrics | Grade-derived metrics have no hourly data to bucket; the split makes them measurable |
| LLM-judge reproducibility | Pin model + temperature 0 + rubric version; store the triple; version bump = baseline reset | Leave judge unpinned | An unpinned judge measures the judge's drift, not the system's |
| Chainlit step instrumentation | Explicit context-guarded no-op shim | Trust `cl.step` is a no-op outside context | Removes a pytest dependency on undocumented library-version behavior |
| Gold corpus | Three real, tier-spanning WHO/UNICEF PDFs, checksum-pinned (trust-on-first-use) | Synthetic fixtures; a single document | Measures behavior on the document shape production serves; reproducible without bundling copyrighted files |
| Gold rubric | Weighted, numeric-accuracy-heavy, with refusal questions | Unweighted pass/fail; answer-only | A clinical eval must weight dosing accuracy highest and reward correct declining, not just answering |
| Gold ground-truth trust | Skip unverified expected answers, never score them | Score all and trust the author | A wrong expected answer would manufacture false regressions |
| Gold eval data path | Call real `/chat`, read back `query_audit_log`/`agent_trace_log` | A parallel eval harness | Same lineage path as production; §11.5 made literal again |
| Gold eval grading cost | Deterministic numeric+grounding criteria; pinned judge only for the two qualitative criteria | LLM-judge every criterion | Keeps a full run cheap and its safety-critical criteria fully reproducible |
| Gold eval cadence | Own nightly cron after the grading job, on the shared singleton-guarded scheduler | Reuse an existing cron expression | Reads the grading run's outputs; distinct cadence, one scheduler |
| Gold deviation alerting | Dual (abs-drop OR z-score), per-category and overall, rubric-version-aware baseline | Single overall z-score | A dosing regression must not hide behind a steady overall mean |
| Gold alert transport | Detection built; `emit_alert` transport is a documented binding | Hardcode a Slack/email integration | Same target/alert/owner-without-hardcoded-pager stance as §19.1 |

---

## What ships as code alongside this plan

BC25–BC27's deliverables are provided as a ready-to-integrate package, **`gold_standard/`**, with its own `README.md` written for a novice programmer: corpus manifest + fetch/checksum tooling, the weighted question bank and rubric, the verification pass, the runner and grader, the scheduler job (singleton-guarded), the reporting/deviation-alert layer, the DB migrations, a `crontab.example` and systemd-timer alternative, an `.env.gold.example`, and a single thin `client.py` adapter — the one place the integrator binds the eval to their actual `/chat` endpoint. Follow that README's Step 0→6 to wire it in.
