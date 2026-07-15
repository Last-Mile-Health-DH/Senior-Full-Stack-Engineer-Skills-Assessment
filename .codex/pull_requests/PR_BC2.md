# Pull Request: [BC2] - Database Schema & Alembic Migrations

## 🎯 Executive Summary
BC2 establishes the complete PostgreSQL + pgvector relational schema defined in `ARCHITECTURE.md` §6. The backend now has an Alembic environment, additive versioned migrations for extensions, all core/cache/audit/trace/grading/monitoring tables, the generated `chunks.content_tsv` column, pgvector HNSW indexes, GIN full-text indexing, and the `agentops_summary` read-time view. The test suite verifies clean migration up/down behavior and database-enforced constraints inside the Dockerized backend environment.

## 🛠️ Changes Introduced

### 🖥️ Backend (FastAPI / Database)
- Added `SQLAlchemy`, `alembic`, and `psycopg2-binary` backend dependencies.
- Initialized `backend/alembic.ini`, `backend/alembic/env.py`, and the Alembic script template.
- Declared SQLAlchemy models for documents, chunks, page images, chat history, exact/semantic caches, query audit logs, agent trace logs, response grades, and anomaly flags.
- Added additive Alembic revisions for:
  - `vector` and `pgcrypto` extensions.
  - `documents` and `chunks`, including `VECTOR(1536)`, `content_tsv` as a Postgres generated column, HNSW index, GIN index, and document index.
  - `page_images` with `UNIQUE (document_id, page_number)` and `ON DELETE CASCADE`.
  - `chat_sessions` and `chat_messages` with `source_chunk_ids UUID[]`.
  - `exact_cache`, `semantic_cache`, and semantic HNSW/last-used indexes.
  - `query_audit_log` with unique `idempotency_key` and typed validation/filter status fields.
  - `agent_trace_log`, `response_grade`, and the `agentops_summary` view.
  - `anomaly_flag` with hour-of-day validation and metric index.

### 🎨 Frontend (Next.js / Chainlit)
- No frontend code changes in BC2.

### 🧠 ML & Retrieval (Chunking / Reranking / LLM-Judge)
- Materialized ML-owned retrieval storage decisions into schema: `VECTOR(1536)`, HNSW cosine indexes, generated full-text search column, semantic cache embedding storage, and response grading persistence.
- No retrieval algorithm or threshold changes were made.

## 🧪 Verification and Test Results
Final command:

```sh
docker compose -p assessment exec backend pytest
```

Final output:

```text
collected 19 items

app/tests/test_migrations.py .                                           [  5%]
app/tests/test_repo_hygiene.py ssssssssssss                              [ 68%]
app/tests/test_schema_constraints.py ......                              [100%]

======================== 7 passed, 12 skipped in 2.56s =========================
```

## 📐 Architectural Decisions & Divergences
- Strictly aligned with `ARCHITECTURE.md` §6 and the BC2 workflow in `BUILD_PLAN.md`.
- No architectural divergence was introduced, so no §18 Decision Log entry was required.
- HNSW remains the selected vector index strategy, and `content_tsv` is database-generated rather than application-populated.

## 🤝 Handover Log
- Build Agent handover recorded in `.codex/handover.json`.
- Test Agent handover recorded in `.codex/handover.json`.
- BC2 Definition of Done met: schema exists via Alembic, generated column verified, `agentops_summary` view verified, cascade deletes verified, and migration up/down cycle tested cleanly.
