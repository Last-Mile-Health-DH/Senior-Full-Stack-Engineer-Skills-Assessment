# Gold-Standard Evaluation

This package runs a fixed, versioned clinical RAG regression check against the real `/chat` path. It uses deterministic numeric and citation checks for the safety-critical criteria and the production `JudgeAgent` boundary only for qualitative completeness/safety scoring.

## The corpus: a deterministic matrix of PDF types

The default corpus (`corpus/corpus_manifest.yaml`, `corpus_version: 2.0.0-compact`) is **generated, not downloaded** — four tiny PDFs built deterministically by `corpus/build_compact_corpus.py`. Each is chosen to force a **different branch of the ingestion pipeline**, so the eval proves the system processes each document type correctly, not just one, while staying far inside the app limits (65 MB / 700 pages) and within a free-tier embedding quota:

| Document | Type | Pipeline branch it forces | Verified after ingestion |
|---|---|---|---|
| `dosing_tables.pdf` | ruled tables, native text (one table per page) | structure-aware chunking (**table**) + table-page rasterization | `chunk_strategy = structure_aware` (table kept whole) |
| `treatment_protocol.pdf` | numbered heading hierarchy, native text | structure-aware chunking (**hierarchy**) | `chunk_strategy = structure_aware` (12 headings/page) |
| `referral_guidance.pdf` | flowing prose, no tables/headings | **fixed-size** chunking with 15% overlap | `chunk_strategy = fixed_size` |
| `scanned_dosing_card.pdf` | image only, no text layer | **OCR** fallback extraction | text recovered by OCR; no text layer in the PDF |

Content is authored in the generator, so every gold answer is grounded by construction. The build is byte-deterministic (reportlab `invariant` mode + a pinned PDF date), so the pinned SHA-256 values in the manifest are stable across machines.

The authentic ~659-page WHO corpus (IMCI chart booklet, hospital pocket book, community manual) is preserved in `corpus/corpus_manifest.who.yaml` + `questions.who.yaml`. It exercises the same pipeline on real documents but **cannot be indexed end-to-end on a free-tier hosted embedding key** — the per-day embedding quota is exhausted long before it finishes — so it needs a paid or fresh-project key. The compact corpus exists precisely so the eval is reproducible without that.

## What the questions cover

`questions.yaml` grades seven questions across every retrieval path: table/numeric lookup, semantic prose paraphrase, heading-hierarchy lookup, an **OCR-only** fact, a **cross-document synthesis** question (`source_docs: [dosing_tables, treatment_protocol]` — grounding scores by how many required documents the answer cites), and an out-of-corpus **refusal**.

## Latest run (compact corpus, local Gemini judge)

```
corpus 2.0.0-compact | rubric v1 | judge gemini-3.1-flash-lite (honest fallback; NOT the pinned Opus)
Overall weighted score: 91.12 / 100 | pass-rate 75.0% | 8 scored, 0 skipped
Category: dosing 100 · refusal 100 · synthesis 88.75 · classification 83 · procedure 66.5
```

The full report is committed at [`gold_eval_report.md`](./gold_eval_report.md). Reading it honestly:

- **Perfect (100):** both table/numeric dosing lookups, the OCR-only question (proving OCR end-to-end), the low-lexical-overlap **semantic** question (`semantic_vomiting_drowsy_child` — "throws up" matches "vomits", "sleepy" matches "lethargic"), and the out-of-corpus **refusal** (the system declines cleanly and cites nothing).
- **Passing (88.75):** the cross-document **synthesis** — it cites both source documents and reproduces the amoxicillin dose *and* the 3-day follow-up.
- **Partial (66–66.5):** the two prose questions. They are correctly grounded (grounding 1.0) but earn partial exact-fact credit when the model paraphrases the source wording; the judged completeness criterion carries the nuance.

The number is **not** an Opus-judged baseline: with no Anthropic key the judge falls back to Gemini, which the runner logs loudly and records in the run metadata. Getting here surfaced and fixed several real issues — multi-table pages fragmenting a dosing table (fixed by one-table-per-page so structure-aware chunking keeps each table whole), the generation prompt not declining firmly enough on semantically-adjacent out-of-corpus questions, and the grader measuring grounding/refusal against *retrieved* rather than *cited* chunks.

## Reviewer Status

| Area | Status | Notes |
|---|---|---|
| Package structure | Complete | Corpus manifest, generator, questions, rubric, client, runner, grader, numeric checks, reporting, scheduler adapter. |
| Deterministic tests | Verified complete | `backend/app/tests/test_gold_standard.py` (incl. synthesis-grounding) passes. |
| Compact corpus end-to-end | Verified | All four docs index; per-doc chunk strategy confirmed; eval runs and scores against real `/chat`. |
| Real WHO corpus run | Blocked on quota | Needs a paid/fresh-project embedding key; see `corpus_manifest.who.yaml`. |
| Opus-judged score floor | Not established | Local runs use the Gemini fallback judge and are not comparable to an Opus baseline. Do not gate CI on them. |

## One-Time Corpus Setup

```bash
pip install reportlab pillow          # build dependencies for the generated corpus
python -m gold_standard.fetch_corpus  # builds the generated docs and verifies pinned SHA-256
```

`fetch_corpus` builds any `source: generated` document from `build_compact_corpus.py` and verifies its checksum. (For the WHO corpus, point it at `corpus_manifest.who.yaml`, which downloads by URL instead.) Generated PDFs live in `gold_standard/corpus/files/` and are not committed — the committed, deterministic generator is the source of truth.

## Manual Runs

```bash
python -m gold_standard.runner --trigger manual            # score every verified question
python -m gold_standard.runner --trigger manual --sample 5 # weighted random subset
python -m gold_standard.runner --trigger ci --floor 85     # CI gate (use only with a pinned Opus judge)
```

The runner writes `gold_standard/gold_eval_report.md`, persists `gold_eval_run` and `gold_eval_result`, and links results back to `query_audit_log` when `/chat` returns lineage. Generated reports are local artifacts and should not be committed.

> **Re-indexing note:** if you delete and re-ingest the corpus between runs, clear the answer caches first (`truncate exact_cache, semantic_cache;`) — a cached answer references chunk ids from the previous ingestion, so stale cache entries make citations resolve to nothing. In normal operation a document is immutable once uploaded, so this only arises when rebuilding the corpus.

## Runtime Settings

Use `.env.example` as the source of truth for production variables. The most relevant settings are:

- `GOLD_CHAT_URL`: backend `/chat` endpoint.
- `GOLD_CHAT_AUTH`: optional bearer or service token.
- `GOLD_EVAL_CONCURRENCY`: bounded parallel `/chat` calls.
- `GOLD_EVAL_JUDGE_MODEL`: optional override; defaults to `JUDGE_MODEL`.
- `GOLD_EVAL_CRON`: scheduled run cadence.
- `GOLD_EVAL_DEVIATION_ABS_DROP` and `GOLD_EVAL_DEVIATION_ZSCORE`: alert thresholds.

## Scheduling

The preferred path is the backend scheduler with `ENABLE_SCHEDULED_JOBS=true`; it runs under the Postgres advisory-lock singleton guard. Teams that avoid in-process scheduling can use `crontab.example` or the systemd examples in this directory.
