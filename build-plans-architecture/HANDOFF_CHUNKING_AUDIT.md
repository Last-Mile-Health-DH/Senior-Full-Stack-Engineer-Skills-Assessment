# Handoff: finish the chunking / dedup / audit-trail buildrun

**Branch:** `codex/chat-ui-requirement-polish`
**Last commit:** `bac3cbb feat: dynamic chunking strategy, embedding reuse, and decision-level audit trail`
**State:** code works and is committed. **5 tests fail.** They are expectation drift caused by the new behavior, not (mostly) bugs. Your job is to finish them, verify, and close the remaining items.

Read this whole file before touching anything. The repo rules in `agents.md` still apply: multi-agent loop, update `.codex/handover.json`, log architecture divergences in `ARCHITECTURE (4).md` §18, keep reviewer docs honest.

---

## 0. First: understand the shape of the system

Do not start editing. Spend ten minutes reading these, in this order:

| File | Why |
|---|---|
| `backend/app/api/v1/chat.py` | The whole request pipeline. Note the **fixed ordering**: idempotency claim → input validation → rate limit → cache lookup → retrieval → generation → presenter → output filter → cache write → audit finalize. **Do not reorder it.** Tests pin this and the ordering is a security property (rate limit before cache means a cached query is not a free way past the quota). |
| `backend/app/core/model_router.py` | Which provider answers, per task, from whichever keys exist. |
| `backend/app/documents/chunk_strategy.py` | **New.** How a document gets chunked, and why. |
| `backend/app/documents/chunking.py` → `_embed_with_reuse` | **New.** Why identical text is never embedded twice. |
| `backend/app/agents/tracing.py` → `record_decision` | **New.** Why an answer can be explained after the fact. |

**The one idea that ties it together:** every fallback in this system must be *honest*. If a key is missing, if a model refuses, if retrieval fails — the system degrades and **says so**, in plain language, to the user (`model_status` on the chat response) and to the audit log (`agent_trace_log`). A silently-worse answer is the failure mode we are engineering against. Keep that when you write code.

---

## 1. Environment facts you will trip over (read these or lose an hour)

1. **`docker-compose.yaml` passes an env ALLOW-LIST.** A variable set in `.env` but missing from the `environment:` block **never reaches the container** — the app silently uses the default in `settings.py`. If a setting "isn't taking effect", check this first.
2. **Running `pytest` wipes the database.** The fixtures `alembic downgrade base`. Any document you uploaded is gone. Afterwards run `docker compose -p assessment exec backend alembic upgrade head`, or just restart the backend (the entrypoint migrates).
3. **The backend entrypoint runs migrations on boot.** A broken migration therefore **crash-loops the container**. That is exactly how the `0015` index-name collision showed up.
4. **Changing `backend/requirements.txt` invalidates the pip layer** → a full torch reinstall → ~20 minute rebuild. Avoid adding dependencies. Use `httpx` (already present) for new provider clients.
5. **The local stack runs Gemini** (`gemini-3.1-flash-lite` + `gemini-embedding-001` @ 1536 dims). Anthropic/OpenAI stay as production placeholders. `gemini-2.5-flash` is *listed* by the API but 404s for new keys — verify with `GET /v1beta/models` before pinning any model.
6. **The Gemini key in `.env` is being rotated by the user.** If Gemini calls start 401-ing, that is why. Ask for a new key; do not "fix" the code.

Rebuild loop:
```sh
docker compose -p assessment build backend && docker compose -p assessment up -d backend && sleep 15
docker compose -p assessment exec backend pytest -q
```
For a test-only change you can skip the rebuild:
```sh
docker cp backend/app/tests/<file>.py assessment-backend-1:/usr/src/LMH/app/tests/<file>.py
docker compose -p assessment exec backend pytest app/tests/<file>.py -q
```

---

## 2. The 5 failing tests — diagnosis and exactly what to do

Run this first to see them yourself. **Never fix a test you have not seen fail.**
```sh
docker compose -p assessment exec backend pytest -q 2>&1 | grep '^FAILED'
```

### 2.1 `test_chunking.py::test_chunk_embedding_persistence_populates_vector_and_tsv`
**Symptom:** `assert 2 == 1` — `chunk_count` is 2, test expects 1.

**Cause — this is correct new behavior, not a bug.** The fixture document has no tables and too few headings, so `select_strategy` now picks `FIXED_SIZE` and `flatten_for_fixed_size` converts the heading block into a plain text block. The heading's words are no longer *consumed* as a section label; they are content, so they become their own chunk.

**Do:** update the expectation to 2, and add an assertion that pins *why* — e.g. that `document.metadata_["chunk_strategy"] == "fixed_size"`. A test that just says `== 2` teaches the next reader nothing.
**Do not:** change `flatten_for_fixed_size` to make the old number come back. The old number came from applying structure to a document that has none.

### 2.2 `test_ingestion_agent.py::test_process_document_fallback_preserves_prior_pages_and_logs_metadata`
**Symptom:** `assert 3 == 2` — an extra `agent_trace_log` row named `chunk_strategy_selected`.

**Cause — correct new behavior.** `record_decision` now writes a `decision` row for the chunking strategy. The test counts *all* trace rows and expects only tool calls.

**Do:** filter the query by `event_type = 'tool_call'` so the test asserts what it actually means ("two tools ran, one failed"), and add a separate assertion that the `chunk_strategy_selected` decision row exists. That is a feature — pin it.

### 2.3 `test_chat.py::test_query_audit_finalized_and_source_chunks_persist`
**Symptom:** `assert '0.000003' == '0.000120'` — the cost is different.

**Cause — the test depends on ambient config.** It hardcodes a cost derived from Claude pricing, but the container now routes to `gemini-3.1-flash-lite`, which is cheaper. **The test was always fragile**; the router just exposed it.

**Do:** make the test independent of the environment. `monkeypatch` `settings.model_routing = "manual"` and pin `settings.generation_model_primary`, *or* assert the cost is computed correctly from whatever model was actually used (read `generation_model` from the audit row and recompute) rather than hardcoding a literal. Prefer the second: it tests the *behavior* (cost is derived from the model that ran) instead of a magic number.

### 2.4 + 2.5 `test_cache.py::test_semantic_hit_at_093_and_miss_at_091`, `::test_semantic_hit_count_and_last_used_update`
**Symptom:** `assert None is not None` — the semantic cache lookup returns no hit when it should.

**⚠️ This one is different. Do NOT assume it is expectation drift. Investigate before editing.**

The semantic cache is scoped by `embedding_model` (deliberately — comparing vectors across models is meaningless). The container's `EMBEDDING_MODEL` changed from `text-embedding-3-small` to `gemini-embedding-001`. Two hypotheses, and you must distinguish them:

- **(a) Test-local:** the test writes a cache row with one model name and reads with another, or hardcodes a model string. → fix the test.
- **(b) Real bug:** something in `write_semantic_cache` / `lookup_semantic_cache` reads the model name at a different time or from a different source than the other, so any deployment that changes `EMBEDDING_MODEL` silently loses its whole semantic cache. **If it is this, it is a production bug and matters far more than the test.**

**Do:**
1. Read `backend/app/cache/semantic.py` and check `get_embedding_model()` is called consistently on both the write and lookup paths.
2. Reproduce in isolation: write a row, read it back, print the `embedding_model` column and what the lookup binds.
3. Only then decide whether the fix belongs in the test or the code. Write a regression test for whichever it turns out to be.

---

## 3. After the tests are green

### 3.1 Full verification (all four suites — do not skip any)
```sh
docker compose -p assessment exec backend pytest -q                 # expect: 201 passed, 12 skipped
npm test --prefix frontend -- --runInBand                           # expect: 22 passed
cd frontend && npx tsc --noEmit                                     # expect: clean
python3 -m unittest chainlit_app.tests.test_chat                    # expect: 10 passed
docker compose -p assessment up -d --build frontend chainlit
cd frontend && PLAYWRIGHT_BASE_URL=http://localhost:3000 \
  PLAYWRIGHT_CHAINLIT_BASE_URL=http://localhost:8000 \
  npx playwright test e2e/chat-ui.spec.ts --reporter=list           # expect: 20 passed
```

### 3.2 Prove the new features actually work end to end (not just in unit tests)
The unit tests use fakes. Drive the real thing:

```sh
# 1. Restore schema (pytest wiped it) and upload the gold corpus.
docker compose -p assessment exec backend alembic upgrade head
for f in gold_standard/corpus/files/*.pdf; do
  curl -s -o /dev/null -w "$(basename $f): %{http_code}\n" -X POST -F "file=@$f" \
    http://localhost:6100/api/v1/documents
done
```
Then wait for `status=indexed` (659 pages of OCR + embedding — this takes a while; watch
`docker compose -p assessment logs -f backend`).

**Then verify each claim:**

| Claim | How to prove it |
|---|---|
| Chunking strategy is chosen per document | `SELECT filename, metadata->>'chunk_strategy', metadata->>'chunk_strategy_reason' FROM documents;` — the WHO chart booklet (table-heavy) must be `structure_aware`. |
| Embeddings are reused, not re-paid | Re-upload the *same content* under a different filename (e.g. `cp a.pdf b.pdf`, which changes nothing → document dedup catches it; instead append a byte so the file hash differs but chunks are identical). Then grep the logs for `embedding.reuse` and confirm `embedded=0` or near it. |
| The audit chain replays | Ask a question, take `query_audit_log_id` from the response, then: `SELECT agent_id, tool_name, event_type, score, output FROM agent_trace_log WHERE query_audit_log_id = '<id>' ORDER BY created_at;` — you must see `model_router` (which model, why) and `retrieval_agent` (mode + reranker score). |
| Semantic search actually works | Ask something with **no lexical overlap** with the source wording. If it only works when you use the document's exact words, vector search is dead and you are on the hash fallback — check `embedding.provider` in the logs. |
| Degraded mode is honest | Temporarily blank `GEMINI_API_KEY` in `.env`, restart the backend, ask a question. The chat UI **must** show the amber notice, and `model_status.mode` must be `degraded`. Put the key back. |

---

## 4. What is still NOT done (do these, in order)

1. **Gold-standard evaluation end-to-end.** The corpus is fetched and checksum-pinned (`gold_standard/corpus/corpus_manifest.yaml`), but has never been scored against a real model. After the corpus is indexed:
   ```sh
   python3 -m gold_standard.verify_expected --search    # human-verify expected answers
   python3 -m gold_standard.runner --trigger manual --sample 8
   ```
   **Be honest about the result.** A score over 22 questions whose expected answers were never human-verified is not a quality gate. Report the number *and* what it does not prove. Do not enable the CI score floor (`--floor 85`) until the expected answers are verified — a gate that passes for the wrong reason is worse than no gate.
2. **Confirm the scheduler/cron job** (`gold_standard/crontab.example`, `scheduler_job.py`, `backend/app/scheduling/`). Verify the advisory-lock singleton actually prevents duplicate runs across replicas.
3. **Re-run the ingestion agent's Anthropic path.** It currently 401s on the placeholder key and falls back (correctly). Once a real Anthropic key exists, verify the agentic ingestion loop works rather than always falling back.
4. **Docs.** Update `README.md`, `tests-README.md`, `local-setup.md`, `ARCHITECTURE (4).md` (§18 decision log, §21 assumptions), `SUBMISSION_CHECKLIST_STATUS.md`, `plan.md`, and append `.codex/handover.json` — with the *real* numbers from your run, not these ones.
5. **Push and open the PR.** `git push`; the branch already tracks origin. ⚠️ The `origin` remote has a **PAT embedded in the URL** — it is in git config, not committed, but tell the user to rotate it.

---

## 5. Engineering rules for this repo (non-negotiable)

- **Never fix a test by weakening it.** If a test fails, first decide: is the code wrong, or is the expectation stale? Write down which, then act. Two of the five failures above are the code being *more correct* than the test.
- **Never silently degrade.** Every fallback path must set `model_status`, log a warning naming the missing variable, and be visible in `agent_trace_log`.
- **A missing key is not an error; a placeholder key is not a key.** `_is_real_key` / `model_router.is_real_key` exist because `your-anthropic-api-key-here` is truthy and would otherwise select a client that fails on every call.
- **Do not reorder the `/chat` pipeline.** See §0.
- **Preserve async SQLAlchemy sessions and explicit `text()` SQL.** No raw `asyncpg` in app code.
- **No hosted LLM/embedding calls, and no model-weight downloads, in deterministic tests.** Inject fakes. The reranker weights are baked into the image; `HF_HUB_OFFLINE=1` enforces it.
- **Comments explain *why*, never *what*.** Every comment in the new code states a constraint or a failure mode that the code cannot show on its own. Match that.
- **Report failures faithfully.** If something does not work, say so with the output. The docs in this repo are only useful because they are honest about what is partial.

---

## 6. Known landmines (each of these cost me time — do not rediscover them)

| Landmine | What happens |
|---|---|
| Migration index name collision | `0009` already owns `agent_trace_log_session_idx`. A duplicate name in a new migration **crash-loops the container**, because the entrypoint migrates on boot. Always `CREATE INDEX IF NOT EXISTS` with a *distinct* name. |
| An unhandled 500 escapes CORS | Starlette's error handler sits outside `CORSMiddleware`, so a 500 arrives at the browser as a phantom "No 'Access-Control-Allow-Origin' header". `UnhandledErrorMiddleware` is inside CORS to prevent this. If you see a CORS error, **suspect a 500 first.** |
| Gemini `batchEmbedContents` caps at 100 | More than 100 requests in one call is a bare 400, which failed whole documents. `GeminiEmbeddingClient.BATCH_LIMIT` handles it. |
| Gemini 3 returns `thought: true` parts | Concatenating them splices the model's private reasoning into the chat window. `_first_text` filters them. |
| `MODEL_PRICING_JSON: ${VAR:-}` | Compose passes `""` when unset, which would zero every cost in the audit log. `settings.model_pricing` falls back to a default table on blank. |
| Restarting the backend kills in-flight ingestion | Documents are stranded in `processing` forever. Delete and re-upload them. This is the documented in-process-ingestion limitation. |
| `torch==2.9.1+cpu` is x86_64-only | Pinned unconditionally it makes the image unbuildable on Apple Silicon. Now selected by PEP 508 marker. **Untested on arm64** — do not claim otherwise. |

---

## 7. Definition of done

- [ ] All 5 failing tests resolved, each with a written note saying whether the code or the expectation was wrong.
- [ ] `pytest` green; frontend, Chainlit, `tsc`, and Playwright green.
- [ ] The five end-to-end claims in §3.2 each demonstrated with real output pasted into the docs.
- [ ] Gold eval run, with an honest statement of what the score does and does not prove.
- [ ] Docs and `.codex/handover.json` updated with real numbers.
- [ ] Pushed; PR open; user told to rotate the PAT in the remote URL and the Gemini key.
