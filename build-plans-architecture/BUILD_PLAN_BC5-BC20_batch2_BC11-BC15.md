# Build Plan — Continuation (BC11–BC15)

**Picks up exactly where batch 1 (BC5–BC10) leaves off.** BC5–BC10 took the project from a validated per-page structure assessment through a fully-wired Orchestrator that can call the Retrieval Agent, compact context, and assemble a (still output-filter-stubbed) generation call. This document specifies **BC11 through BC15** — caching, the `/chat` endpoint, the Next.js upload page, real guardrails, and auth/rate-limiting — closing every remaining gap `ARCHITECTURE.md` leaves open in this range, at the same level of executable detail as BC4–BC10.

All conventions from batch 1's "Conventions Every Cycle From BC5 Onward Assumes" section still apply unchanged — repo layout, the standard error envelope, `Settings`, and the `@traced` tracing decorator. Nothing in this batch introduces a second convention system.

**One batch-wide gap found while sequencing this range, resolved here and flagged up front:** `ARCHITECTURE.md` §20 names a single "lightweight scheduled job" that's supposed to handle exact-cache TTL expiry, semantic-cache LRU eviction/invalidation, re-embedding on model-config change, re-running structure detection on config change, the nightly grading job, and anomaly detection — but the traceability table only assigns "§20" to BC20, while BC11's own scope (§9.2) needs cache eviction/invalidation working immediately, not six cycles later. Resolution, logged as a Decision Log row below: **the scheduler infrastructure (APScheduler, in-process) is stood up once, here, at BC11**, running the two jobs BC11 actually needs (exact-cache TTL expiry, semantic-cache LRU cap + invalidation). **BC20 extends the same scheduler** with the remaining jobs (re-embedding, re-ingestion-on-config-change, nightly grading, anomaly detection) rather than building a second scheduling mechanism — one piece of infrastructure, two cycles adding jobs to it, not duplicated.

---

## BC11 — Caching Layer (Exact, Then Semantic)

**Maps to:** §22 cadence item 11 · bonus (caching layer) · `ARCHITECTURE.md` §9.1, §9.2, §9.3, §20 (scheduler infrastructure, first stood up here)
**Owner:** Backend

**Objective:** Implement exact-cache lookup/write (§9.1), semantic-cache lookup/write with cosine similarity gating (§9.2), provider-level prompt caching (§9.3), and the scheduled cache-hygiene job that closes §9.2's previously-unspecified eviction/invalidation gap — size-capped LRU eviction and invalidation on document deletion/re-upload.

**Preconditions:** BC10 complete — the Orchestrator produces a generation-ready draft with the system prefix already correctly ordered before where the cache breakpoint will go.

**New/changed env vars:** `EXACT_CACHE_TTL_SECONDS=86400`, `SEMANTIC_CACHE_ENABLED=true`, `SEMANTIC_CACHE_THRESHOLD=0.92`, `PROMPT_CACHING_ENABLED=true`, `CACHE_BACKEND=postgres`, `CACHE_EVICTION_CRON=0 * * * *`, `ENABLE_SCHEDULED_JOBS=true` (all already declared, first consumed here) plus **new — missing from `.env.example`, added here:** `SEMANTIC_CACHE_MAX_ROWS=5000` — the LRU eviction ceiling `§9.2`'s eviction job needs but that was never declared as a variable anywhere in §23. Default rationale: sized generously above expected per-session query volume for a demo-scale deployment; revisit before a higher-traffic production rollout (same "starting default, not derived from data" honesty §15.3 already models for its own threshold).

**Workflow:**

1. **Exact cache (§9.1):** `normalize_query(query: str) -> str` — lowercase, collapse repeated whitespace, strip leading/trailing whitespace and trailing punctuation. `query_hash = sha256(normalize_query(query).encode()).hexdigest()`. Lookup:
   ```sql
   SELECT answer, source_doc_ids FROM exact_cache
   WHERE query_hash = $1 AND expires_at > now();
   ```
   On hit: return immediately, `cache_status='exact_hit'`, **no retrieval or generation call runs at all** — this is what §7.1's "cache-before-corpus" means literally, not just "cache is checked early."

2. **Semantic cache (§9.2), only on exact-cache miss, only if `SEMANTIC_CACHE_ENABLED`:** embed the query with the same `EMBEDDING_MODEL` used elsewhere (reuse BC5's dimension guard on this embedding too). Nearest-neighbor lookup:
   ```sql
   SELECT id, answer, source_doc_ids, 1 - (query_embedding <=> $1) AS similarity
   FROM semantic_cache
   ORDER BY query_embedding <=> $1
   LIMIT 1;
   ```
   If `similarity >= SEMANTIC_CACHE_THRESHOLD` (0.92): hit — `UPDATE semantic_cache SET hit_count = hit_count + 1, last_used_at = now() WHERE id = $1`, return the cached answer, `cache_status='semantic_hit'`. Below threshold, or no rows: `cache_status='miss'`, proceed to the full pipeline (BC7–BC10).

3. **Cache-write eligibility gate (a real gap, resolved here — new Decision Log row):** `ARCHITECTURE.md` never states whether a filtered/rejected answer could get cached. It clearly shouldn't — a blocked response cached would be served identically, unfiltered, on every subsequent near-duplicate query, silently defeating whatever the filter caught. Resolution: both `write_exact_cache(...)` and `write_semantic_cache(...)` take an explicit `eligible: bool` parameter. **This cycle, with BC14's real output filter not yet built, `eligible` is always `True`** (matching BC10's staged-stub precedent) — but the parameter exists now, clearly flagged in a code comment (`# TODO(BC14): eligible = output_filter_status == "passed"`), so BC14 flips one boolean expression rather than reworking the cache-write call sites.

4. On a full pipeline run: write to `exact_cache` (`query_hash`, `answer`, `source_doc_ids`, `expires_at = now() + EXACT_CACHE_TTL_SECONDS`) **and** `semantic_cache` (`query_embedding`, `representative_query = query` (the original, unnormalized text — useful for later manual inspection), `answer`, `source_doc_ids = list({chunk.document_id for chunk in used_chunks})`, `hit_count = 1`) — both writes happen together, not one-or-the-other, since they serve different lookup paths (exact-string vs. near-duplicate) over the same answer.

5. **Prompt caching (§9.3):** mark the stable system-prompt content block with `cache_control: {"type": "ephemeral"}` as the last block in the system prompt array — BC10 already places the stable prefix before the per-request variable content (chunks, images, question); this cycle is the first to actually set the field. Guard with `PROMPT_CACHING_ENABLED` so it can be toggled off for local cost-free testing without touching the message-assembly code path.

6. **Scheduler infrastructure, stood up here (see the batch-wide gap note above):** `AsyncIOScheduler` (APScheduler) started in FastAPI's `lifespan` handler, gated by `ENABLE_SCHEDULED_JOBS`. Register one job, `cache_hygiene`, on `CACHE_EVICTION_CRON` (`0 * * * *` — hourly):
   ```python
   async def cache_hygiene_job(db_pool):
       # (a) exact_cache TTL expiry
       await db_pool.execute("DELETE FROM exact_cache WHERE expires_at < now();")

       # (b) semantic_cache LRU cap
       await db_pool.execute("""
           DELETE FROM semantic_cache
           WHERE id IN (
               SELECT id FROM semantic_cache
               ORDER BY last_used_at ASC
               OFFSET $1
           );
       """, settings.semantic_cache_max_rows)

       # (c) invalidation on document deletion/re-upload — resolved concretely:
       # this project has no in-place "replace document" endpoint (§4.5 only
       # names upload and delete), so "document changed since cached" and
       # "document deleted" collapse to the same detectable condition: the
       # document_id a cache row's source_doc_ids references no longer
       # resolves in `documents` at all (deleted outright, or superseded by
       # a fresh re-upload that receives a brand-new document_id).
       await db_pool.execute("""
           DELETE FROM semantic_cache sc WHERE EXISTS (
               SELECT 1 FROM unnest(sc.source_doc_ids) AS doc_id
               WHERE doc_id NOT IN (SELECT id FROM documents)
           );
       """)
       await db_pool.execute("""
           DELETE FROM exact_cache ec WHERE EXISTS (
               SELECT 1 FROM unnest(ec.source_doc_ids) AS doc_id
               WHERE doc_id NOT IN (SELECT id FROM documents)
           );
       """)
   ```
   BC20 adds further jobs to this same scheduler instance — it does not create a second one.

7. Cache lookups are **not** wrapped in `@traced` (they run before any agent is consulted, per §7.1 — there's no `agent_name` they belong to). Instead, `cache_status` is returned to the caller (BC12) to write directly onto that turn's `query_audit_log` row.

**Architectural decisions & trade-offs invoked (§18):**
- §9.1/§9.2 — implemented literally; §9.3 prompt caching wired for real, building on BC10's already-correct message ordering.
- **New row:** scheduler infrastructure built once at BC11, extended (not duplicated) at BC20 — resolves the traceability-table ambiguity between "§20 belongs to BC20" and "§9.2's eviction job is needed at BC11."
- **New row:** cache-write eligibility gate (`eligible: bool`) — closes the unspecified "could a filtered answer get cached" question; always-`True` until BC14, by design, not oversight.
- **New row:** document-change invalidation collapses to "referenced `document_id` no longer resolves," since this design has no in-place document-replace endpoint — a simpler, equally correct condition than trying to detect a content-hash change on an id that, in this design, never actually changes out from under a cache row.

**Tests to add this cycle:**
- *Unit:* `normalize_query` collapses whitespace/case/punctuation as specified; identical normalized queries produce identical hashes.
- *Integration:* an exact-cache hit skips retrieval/generation entirely (assert via mock/spy that `RetrievalAgent.run` and the generation call are never invoked).
- *Integration:* a semantic-cache lookup at similarity `0.93` hits; at `0.91` misses (boundary test around the `0.92` threshold) — `hit_count`/`last_used_at` update correctly on hit.
- *Integration:* the LRU-cap job, run against a `semantic_cache` seeded past `SEMANTIC_CACHE_MAX_ROWS`, retains exactly the most-recently-used rows and deletes the rest.
- *Integration:* the invalidation job removes cache rows referencing a deleted document's id, leaves rows referencing still-existing documents untouched.
- *Integration:* exact-cache TTL expiry job removes only rows past `expires_at`.

**Definition of done:**
- [ ] Exact and semantic cache lookup/write implemented and independently tested.
- [ ] `eligible` gate exists on both cache-write functions, flagged for BC14 to wire.
- [ ] Prompt-caching `cache_control` block set, toggleable via `PROMPT_CACHING_ENABLED`.
- [ ] Scheduler stood up, `cache_hygiene` job running all three sub-tasks (TTL, LRU cap, invalidation), each independently tested.
- [ ] `SEMANTIC_CACHE_MAX_ROWS` added to `.env.example` with rationale.

**Suggested commit(s):**
- `feat: implement exact_cache lookup/write with normalized-query hashing`
- `feat: implement semantic_cache lookup/write with cosine-threshold gating`
- `feat: wire prompt-caching cache_control on the stable system prefix`
- `feat: stand up APScheduler, add cache_hygiene job (TTL, LRU cap, invalidation)`
- `test: cache hit/miss, LRU eviction, and invalidation tests`
- `docs: add SEMANTIC_CACHE_MAX_ROWS to .env.example`

---

## BC12 — Chat Endpoint + Chainlit Wiring + Session Persistence + Multimodal Generation

**Maps to:** §22 cadence item 12 · Requirement 1 · `ARCHITECTURE.md` §5, §5.1–§5.6, §8, §12.2 (still stubbed — real filter lands BC14)
**Owner:** Backend (endpoint, session persistence, conversation management), Frontend (Chainlit wiring) — shared

**Objective:** Build `POST /api/v1/chat`, wired to Chainlit, implementing idempotency (§5.5) with real concurrency handling, cache-before-corpus (BC11), session/message persistence (§5.4), the sliding-window-plus-rolling-summary conversation management §8 names but never assigns to a cycle, streaming, and the live agent-trace visualization (§5.6) via `@cl.step`.

**Preconditions:** BC11 complete (cache layer working); BC10 complete (Orchestrator produces an answer given a query).

**New/changed env vars:** `CONVERSATION_WINDOW_TURNS=6`, `CONVERSATION_SUMMARY_TRIGGER_TOKENS=2000`, `MAX_OUTPUT_TOKENS_CHAT=500`, `MAX_OUTPUT_TOKENS_SUMMARY=200`, `ANONYMOUS_CHAT_ALLOWED=true`, `CHAINLIT_AUTH_SECRET` (all declared, first consumed here).

**Workflow:**

1. **Idempotency (§5.5), with concurrency handling made concrete (new Decision Log row — §5.5 named the mechanism but not what "still in flight" actually does):**
   - `turn_seq = (SELECT count(*) FROM chat_messages WHERE session_id=$1 AND role='user') + 1`; `idempotency_key = f"{session_id}:{turn_seq}"`.
   - **The moment `turn_seq` is computed, before any retrieval/generation work starts,** attempt an early `INSERT` of a partial `query_audit_log` row: `(id, session_id, idempotency_key, query, created_at)` with every terminal field (`grounded`, `cost_usd`, `latency_ms`, etc.) left `NULL`.
   - If that `INSERT` raises a `unique_violation` (Postgres `23505`), a duplicate request for this exact turn is already in flight or already complete. Read the existing row by `idempotency_key`: if its terminal fields are populated, return that result immediately (no new work). If not yet populated, **poll the row every 250ms up to a 10s timeout**; return the result once it completes, or return `202 Accepted` with a `Retry-After` hint if the timeout elapses (the original request is presumably still processing and will finish independently).
   - The `UNIQUE` constraint on `idempotency_key` (§6, BC2) is the actual enforcement mechanism — this cycle is where it gets exercised by a real code path, not just a schema property.

2. **Cache check (BC11), immediately after the idempotency claim succeeds, before any retrieval:** exact then semantic. On hit, populate the placeholder `query_audit_log` row's `cache_status` and skip straight to persistence + streaming (step 6).

3. **On cache miss — load and manage conversation history (§8, previously unassigned to any cycle — new Decision Log row for the concrete trigger mechanics):**
   - A "turn" = one `user` message + its paired `assistant` message. The **sliding window** keeps the last `CONVERSATION_WINDOW_TURNS` (6) turns verbatim (12 `chat_messages` rows).
   - Before assembling the prompt, compute the token count of everything **older** than the window. If it exceeds `CONVERSATION_SUMMARY_TRIGGER_TOKENS` (2000) **and** isn't already fully covered by the most recent `system_summary` row, refresh the summary: fetch the latest `system_summary` row (if any) plus every raw turn older than the window not yet folded into it, call `GENERATION_MODEL_FAST` with a fixed summarization prompt ("condense the following conversation history into a brief factual summary, preserving anything the user might refer back to"), capped at `MAX_OUTPUT_TOKENS_SUMMARY` (200) output tokens, and insert the result as a new `chat_messages` row (`role='system_summary'`) — the previous summary row is left in place (append-only history), but only the **most recent** `system_summary` row is ever read when assembling context.
   - Context assembly for the generation call: `[latest system_summary content, if any] + [windowed turns, verbatim, chronological] + [current user question]` — the summary is injected as a leading synthetic turn, not folded into the system prompt (keeps §9.3's stable-prefix caching untouched by per-session content).

4. **Delegate to the Orchestrator (BC10)** with the assembled conversation context plus the current query — `consult_retrieval_agent` runs, generation is assembled, the (still-stubbed) output filter runs.

5. **Live agent-trace visualization (§5.6), implemented as decorator stacking on the already-traced functions — not a separate instrumentation pass:**
   ```python
   @cl.step(type="tool")
   @traced(agent_name="retrieval_agent")
   async def hybrid_search(...): ...
   ```
   applied to `hybrid_search`, `rerank`, `expand_query`, `fetch_page_image` (`type="tool"`), the generation call (`type="llm"`), and the output filter (`type="tool"`), matching §5.6's own step-naming table exactly. **Implementation wrinkle, resolved here:** `cl.step` only does anything meaningful inside an active Chainlit run context — the same functions are also called directly from `pytest` (BC5–BC10's own test suites) with no such context present. Resolution: `cl.step`'s decorator is a no-op outside a Chainlit context by Chainlit's own design (confirmed at implementation time against the installed Chainlit version — flag and log in §18 if the installed version behaves otherwise), so no conditional wrapping is needed; this is called out explicitly here so a junior developer doesn't spend time building an unnecessary guard.

6. **Persist and finalize (§5.2, §5.4):** insert the `assistant` `chat_messages` row (`content`, `source_chunk_ids = [c.id for c in used_chunks]`); update the placeholder `query_audit_log` row with every remaining field (`retrieved_chunk_ids`, `reranked`, `retrieval_mode` = `'deterministic'`/`'agentic_expanded'` from `RetrievalResult.expanded`, `generation_model`, `grounded`, `output_filter_status`, `latency_ms`, `token_input`, `token_output`, `cost_usd` computed from the provider's usage response times the configured per-token rate).

7. **Stream** tokens to the Chainlit client as generated (native Chainlit streaming, unchanged from the original design).

8. **Empty and error states (§5.3):** before doing any of the above, `SELECT count(*) FROM documents WHERE status='indexed'` — if zero, respond with a friendly upload-first prompt, no retrieval attempted. A caught `RetrievalUnavailableError` (BC10) surfaces as the honest, specific error message §14 requires, streamed to the user like any other message, not swallowed or shown as a blank response.

**Architectural decisions & trade-offs invoked (§18):**
- **New row:** idempotency concurrency handling — `UNIQUE`-constraint-triggered polling with a bounded timeout, resolving what "the client's existing poll/stream continues" concretely does.
- **New row:** conversation-window/summary trigger mechanics — a turn-pair sliding window plus a refresh-on-threshold rolling summary, stored as append-only `system_summary` rows with only the latest read back — closes §8's "no owning cycle, no stated trigger mechanics" gap.
- §5.6 — implemented via decorator stacking on already-existing traced functions, exactly matching the architecture doc's "one function body, no duplicated instrumentation" framing.
- §12.2 stub — still carried forward from BC10, still explicitly flagged pending BC14 (repeated here deliberately, not left implicit, since this is the cycle where a reviewer would otherwise reasonably expect it to be real).

**Tests to add this cycle:**
- *Integration:* a duplicate `/chat` request with the same `session_id`/`turn_seq` (simulated double-submit) returns the same result as the original without triggering a second generation call.
- *Integration:* two concurrent duplicate requests (simulated via `asyncio.gather` against the same idempotency key) — exactly one reaches generation; the other polls and returns the same final result.
- *Unit:* conversation-window/summary trigger fires exactly when accumulated pre-window token count crosses `CONVERSATION_SUMMARY_TRIGGER_TOKENS`, not before; only the most recent `system_summary` row is read back into context.
- *Integration:* a cache hit (BC11) never invokes `RetrievalAgent.run` or the generation call (spy/mock assertion).
- *Integration:* empty-corpus state returns the upload-first prompt without attempting retrieval.
- *Integration:* a forced `RetrievalUnavailableError` streams an honest error message to the (mocked) Chainlit client, not a blank or generic one.

**Definition of done:**
- [ ] `/chat` idempotency enforced via the `UNIQUE` constraint, with real polling/timeout behavior for concurrent duplicates.
- [ ] Cache check runs before any retrieval, on every non-duplicate request.
- [ ] Sliding window + rolling summary implemented and tested against the stated trigger condition.
- [ ] `@cl.step` stacked onto every already-traced pipeline function per §5.6's naming table.
- [ ] Session/message/citation persistence and full `query_audit_log` row finalization confirmed.
- [ ] Empty-state and error-state messages match §5.3, never blank/generic.

**Suggested commit(s):**
- `feat: implement /chat idempotency (UNIQUE-constraint claim + poll-on-duplicate)`
- `feat: wire exact/semantic cache check before retrieval on every chat turn`
- `feat: implement sliding-window + rolling-summary conversation management`
- `feat: stack @cl.step onto agent tool functions for live trace visualization`
- `feat: persist session/message/citation data, finalize query_audit_log rows`
- `test: idempotency race, conversation-summary trigger, cache-skip, and empty/error-state tests`

---

## BC13 — Next.js `/documents` Upload Page (Frontend)

**Maps to:** §22 cadence item 13 · Requirement 2 · `ARCHITECTURE.md` §4.5
**Owner:** Frontend

**Objective:** Build the dedicated `/documents` route: drag-and-drop/file-picker upload with client-side pre-validation mirroring §4.1, upload progress, a polling document list, delete action, and an empty state — against the `POST/GET/DELETE /api/v1/documents*` endpoints BC3 already built.

**Preconditions:** BC3 complete (`/api/v1/documents*` endpoints exist and return real status).

**New/changed env vars:** none in `.env.example` (backend config) — **new, in a separate `frontend/.env.local.example` file (Next.js convention, not the backend's `.env.example`):** `NEXT_PUBLIC_API_BASE_URL=http://localhost:6100/api/v1`. This closes a real gap: `ARCHITECTURE.md` §23 never names how the Next.js app learns the backend's URL, and Next.js's `NEXT_PUBLIC_`-prefix requirement for client-exposed env vars means it can't simply reuse the backend's `.env` file even if colocated. Logged as a Decision Log row below.

**Workflow:**

1. **Avoid duplicating upload limits as separate frontend constants (new Decision Log row):** rather than hard-coding `MAX_PDF_SIZE_MB`/`MAX_PDF_PAGES`/`ALLOWED_MIME_TYPES` a second time in frontend code (which would silently drift from the backend's `.env.example` values the moment either changes), add a small, public, read-only endpoint to BC3's router:
   ```python
   @router.get("/config/upload-limits")
   async def get_upload_limits() -> UploadLimitsResponse:
       return UploadLimitsResponse(
           max_size_mb=settings.max_pdf_size_mb,
           max_pages=settings.max_pdf_pages,
           allowed_mime_types=[settings.allowed_mime_types],
       )
   ```
   The `/documents` page fetches this once on mount and uses it for client-side validation — one source of truth, no drift possible.

2. **Drag-and-drop / file-picker upload** (native HTML5 drag/drop API, or `react-dropzone` if already a starter-repo dependency — don't add a new dependency for this if the native API suffices at this scope).

3. **Client-side pre-validation, explicitly UX-only, never a substitute for the server-side magic-byte check (§4.1) — reaffirmed here, not re-decided:** on file select, check `file.type === 'application/pdf'` and `file.size <= maxSizeMb * 1024 * 1024` against the values fetched in step 1; on failure, show an inline error immediately and **do not** issue the upload request at all.

4. **Upload with progress:** `axios` (or `XMLHttpRequest` directly, since `fetch` has no native upload-progress event) with `onUploadProgress` driving a progress bar; on success, add the returned `document_id`/`status='processing'` to local state immediately (optimistic) rather than waiting for the next poll cycle.

5. **Status polling:** every 2s, `GET /api/v1/documents/{id}` for any document still `status='processing'`; stop polling that document once it reaches `indexed` or `failed`. `GET /api/v1/documents` (list) refreshes the full table on mount and after any upload/delete.

6. **Document list:** filename, upload date, page count, status (with a small spinner/badge for `processing`, error styling for `failed`).

7. **Delete action:** confirm dialog → `DELETE /api/v1/documents/{id}` → optimistic removal from the list, rolled back with an inline error if the request fails.

8. **Empty state:** when the list is empty, show an upload-first prompt directing the user to add a document before starting a chat — matches §5.3's chat-side empty state as the other half of the same user journey.

9. **Auth header, staged for BC15 (same precedent as BC3/BC10's stubs):** every fetch call attaches an `Authorization: Bearer <token>` header sourced from a placeholder `getSessionToken()` helper that currently returns `null`/an empty stub — so BC15 only has to implement `getSessionToken()` for real, not rework every call site.

**Architectural decisions & trade-offs invoked (§18):**
- **New row:** `NEXT_PUBLIC_API_BASE_URL` as a frontend-only env var in `frontend/.env.local.example`, separate from the backend's `.env.example` — closes a gap `ARCHITECTURE.md` §23 never addresses (how the frontend learns the backend's URL).
- **New row:** upload limits served from a backend config endpoint rather than duplicated as frontend constants — avoids the two independently-maintained copies drifting.
- §4.1 — client-side validation reaffirmed as UX-only; the actual security boundary is BC3's server-side magic-byte check, unchanged.

**Tests to add this cycle (Jest + RTL):**
- Renders the dropzone and empty state when the document list is empty.
- Client-side validation rejects an oversized or wrong-MIME file **before** any network call — assert the mocked `fetch`/`axios` call was never made.
- Progress indicator updates as `onUploadProgress` events fire (mocked).
- Status polling transitions a row from `processing` to `indexed` in the UI (mocked poll responses).
- Delete action removes the row optimistically and rolls back on a mocked failure response.

**Definition of done:**
- [ ] `/documents` route implemented with upload, progress, polling list, delete, and empty state.
- [ ] Client-side validation reads limits from `/config/upload-limits`, no duplicated constants.
- [ ] `NEXT_PUBLIC_API_BASE_URL` documented in `frontend/.env.local.example`.
- [ ] Auth header stub in place, ready for BC15.
- [ ] All tests above passing.

**Suggested commit(s):**
- `feat: add GET /config/upload-limits backend endpoint`
- `feat: build /documents page — dropzone, progress, validation against config endpoint`
- `feat: add status polling, document list, delete action, empty state`
- `chore: add frontend/.env.local.example with NEXT_PUBLIC_API_BASE_URL`
- `test: upload validation, progress, polling, and delete tests (Jest + RTL)`

---

## BC14 — Guardrails: Input Validation, Injection Defense at Tool-Result Boundaries, Real Output Filtering

**Maps to:** §22 cadence item 14 · Requirement 3 (secure) · `ARCHITECTURE.md` §12.1, §12.3, §12.4
**Owner:** Backend

**Objective:** Replace BC10/BC12's always-pass output-filter stub with the real three-check filter (§12.2, referenced from §12.1's cross-check framing), formalize input validation as a non-optional hook on every route (Kernel Invariant 1, §15.1), and make §12.1's tool-result prompt-injection defense concrete code, not just a stated principle — closing the one place `ARCHITECTURE.md` names a defense without ever specifying its mechanism.

**Preconditions:** BC12 complete — `/chat` exists, output-filter stub wired into both the Orchestrator (BC10) and the cache-write eligibility gate (BC11).

**New/changed env vars:** none new — consumes existing upload/validation config (`MAX_PDF_SIZE_MB` etc.) already declared.

**Workflow:**

1. **Input validation as a non-optional hook (Kernel Invariant 1, §15.1) — formalized, not per-endpoint opt-in:** attach `Depends(validate_request)` at the `APIRouter` level for every router (`documents`, `chat`, `auth` once BC15 exists), not per-endpoint — a route added later automatically inherits the hook rather than needing to remember to add it. Checks, in order: request-body size ceiling (a hard cap independent of `MAX_PDF_SIZE_MB`, e.g. 25 MB at the ASGI layer, since some routes have no file at all); no embedded null bytes; for `/chat` specifically, message length ≤ 4000 characters. On failure: `422` via the standard error envelope, `code='VALIDATION_ERROR'`, and — for chat — `query_audit_log.input_validation_status='rejected'` written on that turn's placeholder row (BC12) before anything else runs.

2. **Real output filter (§12.2), replacing the stub — four checks, in order, any failure short-circuits the rest:**
   - **Grounding check:** reuses BC10's `compact_chunk` term-overlap scorer (a deliberate reuse, not a second algorithm to maintain) — for each sentence in the generated answer, compute overlap against the union of terms in the chunks actually cited; if the **maximum** per-sentence overlap score across the whole answer falls below `0.15` (a fixed, documented threshold), `output_filter_status='filtered'`, `output_filter_reason='grounding_fail'`.
   - **Leak check:** a fixed set of canary substrings drawn from the system prompt and tool schemas (e.g., literal tool names, internal instruction phrasing) checked via case-insensitive substring match against the answer; a hit sets `output_filter_reason='leak_check_fail'`.
   - **PII check:** regex-based scan (email, phone, US-SSN-shaped patterns) over the answer; a match is only a failure if that exact PII string does **not** appear anywhere in the retrieved source chunks used for this answer — PII genuinely present in the source document (e.g., a clinic contact template) is not itself a violation; PII the model appears to have introduced from elsewhere is. `output_filter_reason='pii_check_fail'`.
   - **Length/format check:** `MAX_OUTPUT_TOKENS_CHAT` is already enforced at generation time via the `max_tokens` parameter; this check only confirms the answer isn't empty/whitespace-only. `output_filter_reason='length_fail'`.
   - On any failure: **never send the raw answer.** Return a fixed, honest fallback message ("I wasn't able to verify that answer against your documents closely enough to share it — could you rephrase, or check the source directly?") — per §14, never a blank or silently degraded response.

3. **Tool-result prompt-injection boundary, made concrete (§12.1 — new Decision Log row, since the architecture doc states the principle but never the mechanism):** implement `sanitize_tool_result(text: str) -> str` — strips/escapes substrings matching role-marker or instruction-injection patterns (`"System:"`, `"Ignore previous instructions"`, and critically, any literal `</context>` or `<context` sequence appearing **inside retrieved content itself**, since a malicious PDF could contain that exact delimiter text attempting to break out of §12.1's own XML-style wrapper). Applied at exactly the two points attacker-controlled text can enter a `tool_result` block: `hybrid_search`'s returned chunk `content` field, and `expand_query`'s free-text `reason` field (the model's own reasoning, which could in principle echo injected text back). Every other tool's output is either purely structural (booleans, ids, bounding boxes) or already sanitized upstream, so it isn't a re-entry point.

4. **Standard API hardening (§12.4):** `CORSMiddleware` restricted to `CORS_ALLOWED_ORIGINS`; response headers `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` added globally via middleware; request-body size limit at the ASGI/reverse-proxy layer (the concrete value is set here, enforced for real at BC18's deployment config). **Cross-reference, not re-decided:** BC9's "`fetch_page_image` has no public route" decision is added to this cycle's hardening checklist as a confirmed-still-true item, not re-litigated.

5. **Wire the real filter into both consuming call sites**, closing the TODOs both left open for exactly this cycle: BC10's Orchestrator generation call site, and BC11's cache-write `eligible` parameter (`eligible = (output_filter_status == "passed")`).

**Architectural decisions & trade-offs invoked (§18):**
- **New row:** the grounding check reuses `compact_chunk`'s term-overlap scorer rather than a second embedding-similarity check — one algorithm, zero added inference cost, consistent with §7.2's own "cheap deterministic signal first" philosophy.
- **New row:** `sanitize_tool_result` — concrete implementation of §12.1's stated-but-unspecified tool-result boundary, applied at exactly the two tool outputs where attacker-controlled text can appear.
- §12.4 — standard hardening, cross-referencing rather than duplicating BC9's access-boundary decision.

**Tests to add this cycle:**
- *Unit:* grounding check passes an answer whose sentences genuinely overlap cited-chunk terms; fails a fabricated/ungrounded answer with no such overlap.
- *Unit:* leak check catches a canary substring embedded in a (test-only) generated answer.
- *Unit:* PII check flags PII absent from source chunks; does **not** flag PII present verbatim in a cited source chunk.
- *Integration:* a chunk whose stored content contains a literal `</context><system>...` string is fully sanitized before ever reaching a `tool_result` block — assert on the sanitized value, not just that generation "worked."
- *Integration:* a filtered response is never written to `exact_cache`/`semantic_cache` (direct test of the `eligible` wiring closed this cycle).
- *Integration:* oversized/malformed `/chat` request body rejected with `422` and `input_validation_status='rejected'` recorded on the turn's audit row before any retrieval work starts.

**Definition of done:**
- [ ] Input validation is a router-level dependency, not per-endpoint opt-in; a new route inherits it automatically.
- [ ] All four output-filter checks implemented, each independently tested, with typed `output_filter_reason` values matching §6's schema.
- [ ] `sanitize_tool_result` applied at both identified injection-entry points; the delimiter-escape test passes.
- [ ] Standard hardening headers/CORS confirmed via test.
- [ ] BC10 and BC11's stub/TODO wiring both replaced with the real filter — no remaining "always passes" code path.

**Suggested commit(s):**
- `feat: formalize input validation as a router-level dependency (Kernel Invariant 1)`
- `feat: implement real output filter (grounding, leak, PII, length checks)`
- `feat: implement sanitize_tool_result, apply at hybrid_search and expand_query boundaries`
- `feat: add CORS/security-header hardening middleware`
- `feat: wire real output filter into Orchestrator and cache-write eligibility gate`
- `test: guardrail unit tests, tool-result injection test, cache-eligibility integration test`

---

## BC15 — Authentication + Rate Limiting

**Maps to:** §22 cadence item 15 · Requirement 3 (secure) · `ARCHITECTURE.md` §12.0, §13
**Owner:** Backend

**Objective:** Implement lightweight JWT session auth for upload/document-management endpoints (chat stays open, per an explicit, now-code-backed README decision), and rate limiting — the existing per-session cap **plus the previously-missing per-IP ceiling** — enforced before the cache lookup.

**Preconditions:** BC14 complete — guardrails are real, not stubbed, so auth/rate-limit failures return through the same standard error envelope as every other guardrail rejection.

**New/changed env vars:** `JWT_SECRET`, `SESSION_TOKEN_EXPIRY_MINUTES=60`, `ANONYMOUS_CHAT_ALLOWED=true`, `RATE_LIMIT_PER_SESSION_PER_HOUR=30`, `RATE_LIMIT_WINDOW_SECONDS=3600` (all already declared, first consumed here) plus **new — missing from `.env.example`, added here:** `RATE_LIMIT_PER_IP_PER_HOUR=100` — the per-IP ceiling `ARCHITECTURE.md`'s own revision note names as a "secondary gap closed" but never actually specifies a variable for. Default rationale: a coarser ceiling than the per-session limit, defending against many-sessions-from-one-source abuse a per-session cap alone can't catch; set above the per-session cap times a reasonable few-tabs-open multiple, not equal to it, so ordinary multi-session use from one household/office IP isn't penalized.

**Workflow:**

1. **JWT session issuance:** `POST /api/v1/auth/session` issues a signed JWT (`HS256`, `JWT_SECRET`), `sub` = a generated anonymous identifier, `exp = now + SESSION_TOKEN_EXPIRY_MINUTES`. No username/password — per §21 assumption 6 (single-tenant, no multi-org isolation) and §18's existing "lightweight JWT over full OAuth2/SSO, right-sized for a demo" decision, this token proves "a client of this app," not a specific human identity; OAuth2/SSO remains the named production next step, unchanged.

2. `require_auth` FastAPI dependency verifies signature + expiry; attached to `/api/v1/documents*` per §12.0. **`/api/v1/chat` is explicitly not behind this dependency when `ANONYMOUS_CHAT_ALLOWED=true`** — this is the cycle where §12.0's "chat endpoint openness is an explicit README decision, not left ambiguous" becomes real code (and gets written into the `README.md` stub for BC19 to expand, not left as a doc-only claim).

3. **Rate limiting middleware, applied before the cache lookup (§13), reusing `query_audit_log` as the counter store rather than adding Redis or an in-memory structure (a deliberate "don't add infrastructure this scale doesn't need" call, consistent with §18's existing Postgres-first caching decision):**
   - Per-session: `SELECT count(*) FROM query_audit_log WHERE session_id=$1 AND created_at > now() - interval '1 hour'`; breach → `429`.
   - **Per-IP (new — closes the ceiling gap):** requires a `client_ip` column on `query_audit_log`, which doesn't exist yet — **add it via a new, additive Alembic migration in this cycle** (`ALTER TABLE query_audit_log ADD COLUMN client_ip INET;`), populated from `request.client.host` (or the first entry of `X-Forwarded-For` when running behind BC18's load balancer — noted here, wired for real at BC18). Same counting approach: `SELECT count(*) FROM query_audit_log WHERE client_ip=$1 AND created_at > now() - interval '1 hour'`; breach → `429`.
   - On breach of either: `429`, standard error envelope, `code='RATE_LIMIT_EXCEEDED'`, `Retry-After` header computed from the oldest row inside the current window.
   - `/api/v1/documents` (uploads specifically) rate-limited independently via a distinct bucket key (`upload:{session_id}`) at a lower ceiling, to bound storage-abuse risk separately from chat-request volume — same middleware, different key/limit pair, not a second implementation.

4. `CORS_ALLOWED_ORIGINS` enforcement (wired in BC14) confirmed working end-to-end with real auth headers present, closing the loop on this cycle's security surface.

**Architectural decisions & trade-offs invoked (§18):**
- §12.0 — lightweight JWT, unchanged in spirit, now a concrete issuance endpoint + dependency.
- **New row:** per-IP rate-limit ceiling added alongside the per-session one, with the concrete default and the `client_ip` schema addition it requires — one of the architecture doc's own named-but-unspecified "secondary gaps."
- **New row:** rate-limit counters reuse `query_audit_log` rather than a new counter table or Redis — same "simpler to operate at this scale" reasoning §18 already applies to the response-cache backend choice, extended here.

**Tests to add this cycle:**
- *Integration:* `require_auth` rejects a missing/expired/malformed JWT on `/api/v1/documents*` with the standard error envelope; accepts a valid one.
- *Integration:* `/api/v1/chat` remains reachable with no `Authorization` header when `ANONYMOUS_CHAT_ALLOWED=true`.
- *Integration:* exceeding `RATE_LIMIT_PER_SESSION_PER_HOUR` returns `429` with a `Retry-After` header; a different session from the same IP is unaffected until the per-IP ceiling is also breached.
- *Integration:* exceeding `RATE_LIMIT_PER_IP_PER_HOUR` returns `429` even when spread across multiple distinct `session_id`s from that IP.
- *Integration:* the upload-specific rate bucket is enforced independently of the chat bucket for the same session.

**Definition of done:**
- [ ] `POST /api/v1/auth/session` issues a valid JWT; `require_auth` correctly gates document-management routes.
- [ ] `/chat` confirmed reachable without auth per the `ANONYMOUS_CHAT_ALLOWED` flag.
- [ ] Per-session **and** per-IP rate limits enforced before the cache lookup, both independently tested.
- [ ] `client_ip` column added via a proper additive Alembic migration, not a hand-edited schema change.
- [ ] `RATE_LIMIT_PER_IP_PER_HOUR` added to `.env.example` with rationale.

**Suggested commit(s):**
- `feat: implement JWT session issuance and require_auth dependency`
- `feat: gate /api/v1/documents* behind auth, confirm /chat stays open per ANONYMOUS_CHAT_ALLOWED`
- `feat: add client_ip column (migration), implement per-session and per-IP rate limiting`
- `feat: add upload-specific rate-limit bucket`
- `test: auth gating, per-session and per-IP rate-limit tests`
- `docs: add RATE_LIMIT_PER_IP_PER_HOUR to .env.example`

---

## Decision Log Rows Added in This Batch (fold into `ARCHITECTURE.md` §18 at BC19)

| Decision | Choice | Alternative considered | Why |
|---|---|---|---|
| Scheduler infrastructure timing | Stood up once at BC11 (cache hygiene), extended at BC20 (grading/anomaly/re-embedding) | Build the full scheduler once at BC20 only | BC11's own §9.2 scope needs eviction/invalidation working immediately, not six cycles later |
| Cache-write eligibility | Explicit `eligible: bool` gate on both cache-write functions, always `True` until BC14 | Wire the real filter check into BC11 directly | BC14 doesn't exist yet at BC11; the gate makes the future wiring a one-line change, not a rework |
| Semantic-cache invalidation condition | "Referenced `document_id` no longer resolves in `documents`" | Track and compare `content_hash` per cache row | This design has no in-place document-replace endpoint, so delete-or-re-upload always changes the id; simpler condition, same correctness |
| `/chat` idempotency concurrency handling | `UNIQUE`-constraint-triggered claim + bounded polling on duplicate | Application-level distributed lock | Reuses a constraint the schema already has; no new locking infrastructure |
| Conversation window/summary trigger | Turn-pair sliding window (6) + refresh-on-threshold rolling summary, only the latest summary row read back | Summarize every turn on a fixed schedule | Matches §8's "threshold-triggered" framing literally, avoids unnecessary summary-model calls on short sessions |
| Frontend backend-URL configuration | `NEXT_PUBLIC_API_BASE_URL` in a separate `frontend/.env.local.example` | Reuse the backend's `.env.example` file directly | Next.js's `NEXT_PUBLIC_` prefix requirement for client-exposed vars means the files can't be the same file |
| Frontend upload-limit validation | Fetched from a new `GET /config/upload-limits` endpoint | Duplicate `MAX_PDF_SIZE_MB` etc. as separate frontend constants | Avoids two independently-maintained copies drifting apart |
| Output-filter grounding check | Reuses `compact_chunk`'s term-overlap scorer | A second, embedding-similarity-based grounding check | One algorithm to maintain, zero added inference cost, consistent with §7.2's cheap-signal-first philosophy |
| Tool-result sanitization | `sanitize_tool_result`, applied at `hybrid_search` content and `expand_query` reason fields specifically | A blanket sanitizer on every tool's every field | Every other tool output is structural (booleans/ids/bboxes), not free text an attacker could shape |
| Rate-limit counter storage | Reuses `query_audit_log` via `COUNT(*) ... WHERE created_at > now() - interval` | New in-memory counters or Redis | Consistent with the existing Postgres-first, "simpler to operate at this scale" caching decision |
| Per-IP rate-limit ceiling | New `RATE_LIMIT_PER_IP_PER_HOUR=100`, requires a new `client_ip` column on `query_audit_log` | Infer IP indirectly from session data | `query_audit_log` never stored IP; a small additive migration is cheaper than an inference-based workaround |

---

## Next in This Series

**BC16–BC20** close out the plan: backend test consolidation (deterministic checks, agent-tool tests, then the golden-set eval split by `retrieval_mode` that would calibrate `RETRIEVAL_AGENT_CONFIDENCE_THRESHOLD`) → frontend tests + the table-page-citation Playwright e2e smoke test → deployment config, CI pipeline, and the §19.1 observability target/alert/owner table (named in this document's own revision history but never actually written down — closed at BC18) → the README/docs pass that folds every Decision Log row from this batch and the last back into `ARCHITECTURE.md` → the nightly retrospective-grading and anomaly-detection job, extending BC11's scheduler rather than building a second one.
