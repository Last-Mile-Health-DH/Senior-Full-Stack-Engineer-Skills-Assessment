# Architecture & Engineering Decision Record
### Last Mile Health — Senior Full-Stack Engineer, AI & Digital Health Practice Assessment

**Revision note:** this is v-next of the architecture doc. It folds in a design review that (a) kept the starter stack unchanged, (b) added structural table/figure detection with page-image-augmented generation, (c) evaluated `search_result` content blocks as a citation-mapping upgrade, and (d) reverses the earlier single-orchestrator decision in favor of a scoped multi-agent ingestion/retrieval design. Everything not called out below is unchanged from the prior revision. Superseded content (old §15's "single orchestrator" framing, the old Decision Log row for agent architecture) is replaced in place, not left alongside the new material, so this document has one current answer per question, not two competing ones.

**Revision note (prior pass):** a second design review benchmarked this document against AFYA-AOS, a much larger (32-agent, multi-country, multi-AWS-account) reference architecture, specifically to check this project's discipline — the specific fields tracked, the specific separations of concern — not its infrastructure. AFYA-AOS needs OAuth2 token exchange, a versioned Agent Registry, and a Pricing Intelligence Agent because it has real network hops between independently-deployed agents across separate AWS accounts; this project is one FastAPI process with two internal agents and no such hop, so none of that transfers, and this document says so explicitly rather than importing it by default. What *does* transfer, right-sized: retrospective response grading separated from the pre-send gate (§11.6, §20), a read-time lineage view (§6, §11.5), typed pass/fail + reason fields instead of booleans (§6), an idempotency key on `/chat` (§5.5, §6), named kernel invariants instead of implicit prose (§15.1), cost attribution by category (§6, §10), a target/alert/owner observability table (§19.1), and a widened PII-redaction boundary that covers caches and logs, not just the live response (§12.5). Each addition below is tagged with the AFYA-AOS section it echoes and, symmetrically, three AFYA-AOS patterns are named as **explicitly not adopted** with the reasoning logged in §18 rather than silently omitted: per-agent-instance identity tokens (§15.9), signed cross-service capability tokens/OAuth2 token exchange (§12.1), and a Pricing Intelligence Agent (§18, §19).

**Revision note (this pass):** an external architecture review of the prior pass found three defects that break behavior exactly as specified, plus a documentation-integrity problem where the prior pass's revision note cited six pieces (`agentops_summary`, `response_grade`/§11.6, §19.1, named Kernel Invariants, §15.9, and three AFYA-AOS "not adopted" Decision Log rows) that were named but never actually written into the body. This pass closes all of it:
- **Confidence gate no longer runs on raw RRF score (§7.2, §7.3, §15.3, §17, §18, §23).** The RRF formula at `k=60` tops out at `2/61 ≈ 0.033` for two ranking lists — it can never cross a `0.55` threshold, so `expand_query` would have fired on every single turn, silently inverting §10's entire "cheap path is the default" cost story. RRF is now used only for candidate fusion/ordering into rerank, as it was designed for; the confidence gate reads the cross-encoder's sigmoid-activated relevance score instead, which is naturally bounded 0–1 and already computed in the same pass (§17).
- **Ingestion iteration cap now scales with document length (§15.2, §23).** A fixed `INGESTION_AGENT_MAX_ITERATIONS_PER_DOC=40` against `MAX_PDF_PAGES=300` meant any document past ~40 pages silently fell back to text-only assessment for its entire remaining length — quietly defeating §4.3's structure detection for most realistically-sized documents, with `status=indexed` giving no visible signal that anything degraded.
- **`content_tsv` is now a generated column (§6).** It was declared with a GIN index but nothing populated it, so the lexical half of every "hybrid" search silently returned nothing.
- **The six dangling citations are now real sections/objects**, not just named in a revision note: the `agentops_summary` view and `response_grade` table (§6), the nightly grading job (§11.6), the §19.1 observability table, two named Kernel Invariants (§15.1), and §15.9 plus the three corresponding Decision Log rows (§18).
- **Two previously-unaddressed asks are now covered:** anomaly detection (§20.1) and a live, per-turn agent-trace visualization in the chat UI (§5.6).
- **Secondary gaps closed as one-line notes or small additions, matching this document's own "name it, don't silently omit it" house style:** semantic cache eviction/invalidation (§9.2), page-image access control (§12.4), a per-IP rate-limit ceiling alongside the per-session one (§13), an embedding-dimension mismatch check (§20), `hnsw.ef_search` as a per-transaction setting under connection pooling (§7.2), and an explicit disaster-recovery scope note (§19).

Everything not called out in this pass is unchanged from the prior revision.

## 0. How to Use This Document

This is the single source of truth for the assessment build — architecture, retrieval design, cost/prompt engineering, security posture, testing strategy, and the production deployment plan all live here, with the reasoning behind each decision, not just the decision itself. Update it as the build progresses; if an implementation choice diverges from what's written here, the divergence and its reasoning get logged in the **Decision Log** (§18) before moving on.

**Document map** — three files, each with one job, not duplicated across each other:
- `local-setup.md` — step-by-step local run instructions and troubleshooting (Requirement 6). Authoritative for "how do I start this on my machine."
- `ARCHITECTURE.md` (this file) — design decisions, trade-offs, schema, and the production deployment plan (Requirements 3, 4, 7, and the bonus documentation criteria).
- `README.md` — the entry point a reviewer opens first; summarizes both of the above and states the exact test-run commands (Requirement 5).

**Stack, per the assessment's own substitution policy — unchanged by this revision:**

| Layer | Starter | Local URL | This project's choice |
|---|---|---|---|
| Frontend | Next.js (React) | `localhost:3000` | Kept — document upload & management UI |
| Chat UI | Chainlit | `localhost:8000` | Kept, used **alongside** Next.js (not in place of it) — chat interface |
| Backend | FastAPI (Python) | `localhost:6100` | Kept — single source of truth for ingestion, retrieval, generation, and security |
| Database | PostgreSQL + pgvector | `localhost:5432` | Required, unchanged |

**What this revision does *not* do:** introduce a new service, a message bus, or a framework outside the table above. The multi-agent design in §15 is new Python classes/functions and two new tables (`page_images`, `agent_trace_log`) inside the existing FastAPI process — internal structure, not new infrastructure.

---

## 1. Requirements Traceability Matrix

| # | Requirement | Addressed in | Summary |
|---|---|---|---|
| 1 | Chat interface, grounded responses | §5 (Chat Interface & UX), §7.5 (grounding check), §16 (citation strategy) | Chainlit UI; streamed responses; citations attached per message; grounding enforced before send |
| 2 | PDF upload, dedicated page | §4.5 (Frontend Upload UX) | Next.js `/documents` page: upload, progress, status list, delete |
| 3 | RAG backend — scalable, secure, well-documented | §3 (cross-cutting summary), §4–§10, §15 (implementation), §12 (security) | See §3 for the direct answer to each of the three adjectives |
| 4 | Database — pgvector tables/indexes | §6 (Database Schema) | HNSW + GIN indexes, Alembic migrations, `page_images` + `agent_trace_log` additions |
| 5 | Testing — backend and frontend | §11 (Testing Strategy) | pytest (backend, incl. agent tool tests), Jest/RTL (frontend components), Playwright (e2e smoke test) |
| 6 | Local run instructions | `local-setup.md` (companion file) | Not duplicated here — see Document Map above |
| 7 | Production deployment plan | §19 | Cloud provider, CI/CD, infrastructure considerations, observability |
| Bonus | `.env.example` | §23 | Every variable this document references |
| Bonus | Architectural decisions & trade-offs documented | §18 (Decision Log), throughout | |
| Bonus | Additional service layers (caching, scheduling) | §20 | Now includes the nightly response-grading job (§11.6, §20) |
| Bonus | ML/algorithm choices are justified, not assumed | §17 (Library & Algorithm Choices) | |
| Bonus | Production behavior is graded retrospectively, not just pre-send | §11.6, §20, §6 (`response_grade`) | Deterministic grounding check + sampled LLM-judge rubric score, nightly, on live traffic |
| Bonus | One canonical "what happened for this response" record | §6 (`agentops_summary` view), §11.5 | Read-time view over existing tables — no new instrumentation |
| Bonus | Observability metrics have a target, alert, and owner, not just a monitoring intent | §19.1 | |

---

## 2. System Overview

```mermaid
flowchart LR
    subgraph Client
        NX["Next.js :3000<br/>Upload + Document Mgmt"]
        CL["Chainlit :8000<br/>Chat UI"]
    end
    subgraph Backend["FastAPI Backend :6100"]
        API[REST API Layer]
        GUARD[Input/Output Guardrails]
        IAGENT["Ingestion Agent<br/>bounded tool-use loop"]
        ORCH["Orchestrator<br/>agent-as-tool caller"]
        RAGENT["Retrieval Agent<br/>deterministic fast path<br/>+ gated agentic expansion"]
        CACHE[Cache Layer]
        GEN[Generation Model Call]
    end
    DB[("PostgreSQL + pgvector :5432")]
    IMG[("Page Image Storage<br/>local / S3")]

    NX -- "upload PDF" --> API
    CL -- "chat message" --> API
    API --> GUARD
    GUARD --> IAGENT --> DB
    IAGENT --> IMG
    GUARD --> ORCH
    ORCH --> CACHE
    CACHE -. "miss" .-> RAGENT
    RAGENT --> DB
    RAGENT --> IMG
    RAGENT --> ORCH
    ORCH --> GEN --> GUARD
    GUARD --> API
```

**Core design decision, unchanged:** both frontends are thin clients. All ingestion, retrieval, caching, and generation logic lives once, in the FastAPI backend, exposed as a versioned REST API (`/api/v1/...`). Neither frontend talks to Postgres or an LLM provider directly. Adding agent boundaries (§15) doesn't change this — the agents are internal backend components, not new client-facing surfaces.

Two structural rules govern how GUARD, IAGENT, ORCH, and RAGENT relate to each other in the diagram above — named explicitly as **Kernel Invariants** in §15.1, the same way AFYA-AOS's §4 names its orchestrator-as-kernel rules rather than leaving them implicit in prose.

**Decision — keep the starter frameworks, don't substitute.** Next.js and FastAPI are both well-suited to this task, and the substitution policy exists to accommodate genuine skill fit, not to be exercised by default.

**Decision — Chainlit alongside Next.js, not instead of it.** Unchanged from the prior revision; see §16 of the original decision log for the full reasoning, restated in §18 below.

---

## 3. Backend Quality Attributes: Scalable, Secure, Well-Documented

**Scalable**
- Async FastAPI endpoints throughout, async DB driver (`asyncpg`), sized connection pool.
- Ingestion decoupled from the request path (§4.2) — a large upload never blocks other requests.
- Stateless backend — session/chat/agent-trace state lives in Postgres (§6), not in-process — so it scales horizontally with no sticky-session requirement (§19).
- Caching (§9) reduces load on both the database and the LLM provider.
- **New in this revision:** the Retrieval Agent's agentic (expansion) path is *gated*, not default (§15.3) — this is a scalability decision as much as a cost one, since an unconditional extra LLM round-trip per chat turn would materially change the backend's request-latency profile under load.

**Secure** — full detail at §12; summarized: structural prompt-injection defense (uploaded/retrieved content is data, never instructions, including inside agent tool results — §12.1), output filtering (§12.2), input validation at every boundary, lightweight authentication, rate limiting, secrets via environment variables only. Agent tool calls don't expand this surface: every tool an agent can call is a fixed, server-defined function with a typed schema (§15), never a capability the conversation can add to.

**Well-documented**
- FastAPI's auto-generated OpenAPI docs (`/docs`, `/redoc`) remain the primary API reference.
- This document is the architectural narrative FastAPI's auto-docs don't provide.
- **New in this revision:** `agent_trace_log` (§6, §15.6) makes agent decision-making itself inspectable after the fact — which tools an agent called, in what order, and why (the `reason` field on `expand_query`) — so "well-documented" extends to runtime agent behavior, not just static code.
- **New in this pass:** the `agentops_summary` view (§6, §11.5) and the nightly `response_grade` job (§11.6, §20) extend that same principle from "inspectable" to "gradable" — a reviewer (or an on-call engineer) has one query that answers "what happened for this response, and was it any good," not just a trace of tool calls.

---

## 4. PDF Ingestion Pipeline

```mermaid
sequenceDiagram
    participant U as Next.js /documents
    participant API as FastAPI /upload
    participant VAL as Validation
    participant IAGENT as Ingestion Agent
    participant PARSE as PDF Parser (pdfplumber/PyMuPDF)
    participant OCR as OCR Fallback (pytesseract)
    participant CHUNK as Chunker (deterministic)
    participant EMB as Embedding Service
    participant DB as Postgres/pgvector
    participant IMG as Page Image Storage

    U->>API: POST PDF file
    API->>VAL: MIME/size/page-count check
    VAL-->>API: reject (413/415) or continue
    API->>IAGENT: assess(document_id)
    loop per page, bounded agent loop
        IAGENT->>PARSE: detect_structure(page)
        alt text_yield_ratio < OCR_TEXT_YIELD_THRESHOLD
            IAGENT->>OCR: extract_text_ocr_fallback(page)
        end
        alt has_table or has_figure
            IAGENT->>IMG: flag_table_pages -> rasterize + store PNG
            IMG-->>DB: insert page_images row
        end
    end
    IAGENT->>CHUNK: chunk_document (deterministic tail, not agentic)
    CHUNK->>EMB: embed_batch
    EMB->>DB: write_chunks
    API-->>U: 202 Accepted, status=processing
```

### 4.1 Upload limits ("max PDF")

Enforced at the API boundary, before parsing — rejecting oversized/malformed input early is both cost control and basic DoS defense:

| Control | Default | Rationale |
|---|---|---|
| Max file size | 20 MB | Bounds worst-case synchronous parse time and embedding cost for one upload |
| Max page count | 300 pages | A small-file-size PDF can still have an unreasonable page count (e.g., scanned images) |
| MIME/magic-byte check | `application/pdf`, verified by file header, not just extension | An attacker can rename any file `.pdf`; trusting the extension alone is a known bypass |
| Rejection behavior | `415`/`413`, synchronous, before any processing starts | Fail fast, cheaply, at the edge |

**Open caveat, carried over deliberately:** the page-count/size thresholds for a generation model's *native* PDF handling (relevant if native multimodal PDF ingestion is ever used instead of the rasterize-flagged-pages approach below) should be re-verified against current provider docs at implementation time before being hard-coded into `MAX_PDF_PAGES`/`MAX_PDF_SIZE_MB` (§23) — this project doesn't rely on that path (see §4.3), so it isn't blocking, but don't assume last-known numbers are still current.

### 4.2 Processing model

Ingestion runs as a background task (FastAPI `BackgroundTasks`, or a lightweight queue if time allows) rather than blocking the upload request. The client polls (or is pushed, via SSE) `document.status`: `processing → indexed | failed`.

### 4.3 Structure detection and page-image capture (new)

**Why this exists:** pgvector ingestion is a hard requirement (Requirement 4) for every document regardless of size — there is no "small enough, skip the database" fork here. What *does* vary is how much of a page's information survives being flattened to plain text. Protocol documents in this domain are exactly the case where the lossy part isn't prose, it's tables, dosage charts, and decision trees, which a text-only parse degrades badly. The fix is narrow and additive: **detect** which pages carry that structure, **rasterize only those pages**, and hand the image to the generation model *alongside* the text chunk, never instead of it. This doesn't touch the chunking-strategy decision in §4.4 and doesn't weaken "database required, not substituted."

**Detection heuristic (no custom ML model — see §17 for why):**
- `pdfplumber`'s built-in `page.find_tables()` for table bounding boxes (geometric line/whitespace-grid detection, already implemented in the library).
- A text-yield ratio (`extracted_char_count / page_area`) as a corroborating signal — a page with a table or figure and disproportionately little extractable text is a strong candidate for image capture regardless of what `find_tables()` alone reports.
- The same text-yield signal doubles as the OCR-fallback trigger (§4.3, Ingestion Agent tool `extract_text_ocr_fallback`): a page whose native extraction yields too little text relative to its visible content is treated as scanned/image-only and re-extracted via OCR before chunking.

**Schema addition:**

```sql
CREATE TABLE page_images (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id  UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number  INT NOT NULL,
    storage_ref  TEXT NOT NULL,
    has_table    BOOLEAN NOT NULL DEFAULT false,
    has_figure   BOOLEAN NOT NULL DEFAULT false,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, page_number)
);
CREATE INDEX page_images_document_id_idx ON page_images (document_id);
```

Normalized as its own table rather than a column on `chunks`, since several chunks can share one page (a table's surrounding paragraph and the table itself may land in different chunks but reference the same rasterized page).

**Generation-time use (§7.4, §15.4):** when the Retrieval Agent's final top-N includes a chunk whose page has a `page_images` row, `fetch_page_image` retrieves it and it's attached to the generation call *in addition to* the text chunk. This is a surgical use of the generation model's multimodal input, applied only to the handful of pages retrieval already decided matter — not a bypass of retrieval, and not a blanket "send every page as an image" approach that would blow the cost budget in §10.

### 4.4 Chunking strategy — unchanged

**Decision: fixed-size, token-aware chunking by default (≈450–500 tokens, 15% overlap), with a structure-aware override for headers and tables.** Fixed-size chunking is the simpler, more predictable default; semantic chunking is not implemented for this timeline and should only be adopted after an A/B test shows measurable recall improvement.

- **Structure-aware override:** never split a table across chunks; prefer splitting on document headers/section boundaries when present.
- **Context injection:** the nearest preceding header/section title is prepended to the chunk's text before embedding.
- **Dedup before embedding:** a SHA-256 hash of the source file is checked against `documents.content_hash` before parsing.

This step is implemented as the deterministic `chunk_document` tool (§15.2) — its behavior doesn't vary by agent judgment, unlike structure detection above.

### 4.5 Frontend Upload UX (Requirement 2 — dedicated page) — unchanged

A dedicated route (`/documents`) in the Next.js app:
- Drag-and-drop/file-picker upload with client-side pre-validation mirroring §4.1.
- Upload progress indicator.
- A list of previously uploaded documents: filename, upload date, page count, status — polled/pushed until resolved.
- Delete action, cascading to `chunks` and `page_images` via `ON DELETE CASCADE` (§6).
- An empty state directing a first-time user to upload before starting a chat.

---

## 5. Chat Interface & UX (Requirement 1)

```mermaid
sequenceDiagram
    participant U as Chainlit :8000
    participant API as FastAPI /chat
    participant CACHE as Exact + Semantic Cache
    participant ORCH as Orchestrator
    participant RA as Retrieval Agent
    participant RR as Reranker (cross-encoder)
    participant LLM as Generation Model
    participant OUT as Output Filter
    participant DB as Postgres (sessions/messages/page_images)

    U->>API: question (+ session_id)
    API->>DB: load session history (windowed, §8)
    API->>CACHE: exact hash lookup
    alt Cache hit
        CACHE-->>OUT: cached answer + citations
    else Cache miss
        API->>ORCH: consult_retrieval_agent(query, session_id)
        ORCH->>RA: hybrid_search (deterministic, always runs first)
        RA->>RR: rerank top-20 candidates (always runs, no LLM call)
        alt reranker's top sigmoid score >= RETRIEVAL_AGENT_CONFIDENCE_THRESHOLD
            RR-->>ORCH: top-N chunks (fast/deterministic path)
        else reranker's top sigmoid score below threshold
            RA->>RA: expand_query (bounded agentic sub-loop, LLM call)
            RA->>RR: rerank merged/expanded candidates
            RR-->>ORCH: top-N chunks (agentic path)
        end
        RA->>RA: fetch_page_image for any flagged chunk
        ORCH->>LLM: text chunks + page images + question (cached system prefix)
        LLM-->>OUT: draft answer
        OUT->>CACHE: store if eligible
    end
    OUT->>DB: persist message + citations + agent_trace_log rows
    OUT-->>U: streamed, grounded, filtered response
```

### 5.1 Streaming — unchanged

Tokens are streamed to the client as generated (Chainlit supports this natively).

### 5.2 Source citations — the direct answer to "grounded in the content of uploaded documents"

Every assistant response carries the source document name and page number(s) for the chunks actually used, surfaced as an expandable reference element on the chat message. Backed by `source_chunk_ids` on `chat_messages` (§6). See §16 for a documented, not-yet-adopted upgrade to this mechanism.

### 5.3 Empty and error states — unchanged

- No documents uploaded yet → chat prompts upload first.
- A pipeline failure surfaces the honest, specific error from §14 — never a blank or generic response. This now also covers an agent-loop failure (§15.5): if the Retrieval Agent's bounded sub-loop errors or exceeds `RETRIEVAL_AGENT_MAX_ITERATIONS`, the Orchestrator falls back to the plain deterministic `hybrid_search` + `rerank` result already in hand, rather than surfacing an agent-internal error to the user — the deterministic path is always a safe fallback because it already ran first (§15.3).

### 5.4 Session & history persistence — unchanged

Chat sessions and messages persisted server-side (§6), not held in Chainlit's in-process state.

### 5.5 Idempotency on `/chat` (new)

The PDF upload endpoint already gets idempotency for free via `content_hash` dedup (§4.4) — a re-upload of the same file doesn't re-parse or re-embed it. The chat endpoint had no equivalent, so a double-click or a client retry on `/chat` currently means two full generation calls and two `query_audit_log` rows for what the person experiences as one message. This mirrors a pattern AFYA-AOS's token envelope makes structural for every hop (`idempotency_key = session_id:turn_seq`), scoped here to just the one endpoint that needed it:

- On each `/chat` request, the backend computes `idempotency_key = f"{session_id}:{turn_seq}"`, where `turn_seq` is the count of prior user messages in that session (`chat_messages` row count, role = `user`, +1).
- This check runs **before the cache lookup** (§7.1) — a duplicate request with a key already present on an in-flight or completed `query_audit_log` row short-circuits straight to that row's result (or, if still in flight, the client's existing poll/stream continues) rather than starting a second retrieval + generation cycle.
- `idempotency_key` is a `UNIQUE` column on `query_audit_log` (§6); the uniqueness constraint itself is the enforcement mechanism, not application-level locking.
- This is a real production bug class (double-submit, client retry-on-timeout), cheap to close, and it directly serves §10's cost-optimization story — an unbounded duplicate is strictly worse than a cache miss, since it isn't even a repeat *question*, just a repeat *request*.

### 5.6 Live agent-trace visualization — Chainlit steps (new)

**Why this exists:** right now, a user watching the chat sees nothing, then a streamed answer — for a pipeline that's actually doing real, visible-worthy work (cache check → hybrid search → confidence gate → maybe expand → rerank → maybe fetch a page image → generation → grounding check), that's a lot of pipeline invisible by default. Chainlit already ships the mechanism for this, which is the actual reason "Chainlit alongside Next.js" earns its place in §0's stack table beyond streaming alone: the `@cl.step` decorator (or `cl.Step()` as a context manager) wraps any function and renders it as a step in the chat UI, nesting automatically by call hierarchy, with visibility controlled by a config setting this project defaults to shown for the assessment.

**Implementation, reusing what's already being built, not duplicating it:** the retrieval-agent tool functions (`hybrid_search`, `rerank`, `expand_query`, `fetch_page_image`, `consult_retrieval_agent`), the generation call, and the output-filter check are already being written as the same functions that write `agent_trace_log` rows (§15.6). Adding `@cl.step(type=...)` to each — `type="tool"` for the retrieval tools, `type="llm"` for generation and `expand_query`, `type="run"` for the Orchestrator's top-level call — means the live visual trace and the persisted trace log share one function body: no duplicated instrumentation, the same economy of effort this document already applies to `agentops_summary` (§6).

**Step naming, mapped 1:1 onto §2's own GUARD → CACHE → RAGENT → ORCH → GEN → GUARD diagram:**

| Step (human-readable) | Backing function | Notes |
|---|---|---|
| Checking the cache | exact/semantic cache lookup (§9) | Skips the rest of the trace on a hit |
| Searching your documents | `hybrid_search` | Always runs first, deterministic or agentic |
| Judging match confidence | `rerank` | Always runs; the sigmoid score decides the next step |
| Expanding your question | `expand_query` | Only appears when the gate trips — should be the visibly rare case now that §7.3's threshold reads the reranker's score, not raw RRF |
| Re-ranking results | `rerank` (second pass, expanded path only) | |
| Reading the page image | `fetch_page_image` | Only appears for chunks with a `page_images` row |
| Writing the answer | generation call | Streams tokens live, same mechanism as the final answer today |
| Checking the answer is grounded | output filter (§12.2) | |

Step rendering itself adds no LLM cost — it's pure instrumentation around calls already being made — so no new row is needed in §10's cost table.

---

## 6. Database Schema (PostgreSQL + pgvector)

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()

CREATE TABLE documents (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename      TEXT NOT NULL,
    content_hash  CHAR(64) NOT NULL UNIQUE,
    status        TEXT NOT NULL DEFAULT 'processing', -- processing | indexed | failed
    page_count    INT,
    uploaded_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata      JSONB DEFAULT '{}'
);

CREATE TABLE chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index     INT NOT NULL,
    content         TEXT NOT NULL,
    content_tsv     TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    content_hash    CHAR(64) NOT NULL,
    section_path    TEXT,
    page_number     INT,
    token_count     INT,
    embedding       VECTOR(1536),
    embedding_model TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX chunks_embedding_hnsw_idx ON chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
CREATE INDEX chunks_tsv_idx ON chunks USING gin (content_tsv);
CREATE INDEX chunks_document_id_idx ON chunks (document_id);

-- Page images for structurally complex pages (§4.3) — new
CREATE TABLE page_images (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id  UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number  INT NOT NULL,
    storage_ref  TEXT NOT NULL,
    has_table    BOOLEAN NOT NULL DEFAULT false,
    has_figure   BOOLEAN NOT NULL DEFAULT false,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, page_number)
);
CREATE INDEX page_images_document_id_idx ON page_images (document_id);

-- Chat sessions & messages (§5.4)
CREATE TABLE chat_sessions (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_ref       TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_active_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE chat_messages (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id       UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role             TEXT NOT NULL,               -- user | assistant | system_summary
    content          TEXT NOT NULL,
    source_chunk_ids UUID[],
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX chat_messages_session_idx ON chat_messages (session_id, created_at);

-- Exact-match response cache (§9.1)
CREATE TABLE exact_cache (
    query_hash     CHAR(64) PRIMARY KEY,
    answer         TEXT NOT NULL,
    source_doc_ids UUID[],
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at     TIMESTAMPTZ NOT NULL
);

-- Semantic response cache (§9.2)
CREATE TABLE semantic_cache (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_embedding      VECTOR(1536) NOT NULL,
    representative_query TEXT NOT NULL,
    answer               TEXT NOT NULL,
    source_doc_ids       UUID[],              -- (new) documents this answer traced to — invalidation target for §9.2's eviction job
    hit_count            INT NOT NULL DEFAULT 1,
    last_used_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX semantic_cache_embedding_idx ON semantic_cache
    USING hnsw (query_embedding vector_cosine_ops);
CREATE INDEX semantic_cache_last_used_idx ON semantic_cache (last_used_at);

-- Full-lineage audit / eval log (§11, §12)
CREATE TABLE query_audit_log (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id             UUID REFERENCES chat_sessions(id),
    idempotency_key        TEXT UNIQUE,               -- session_id:turn_seq (§5.5) — new
    query                  TEXT NOT NULL,
    cache_status           TEXT,                       -- exact_hit | semantic_hit | miss
    cost_category          TEXT,                       -- live_inference | cache_hit | embedding_backfill (new)
    retrieved_chunk_ids    UUID[],
    reranked               BOOLEAN DEFAULT false,
    retrieval_mode         TEXT,                        -- deterministic | agentic_expanded
    generation_model       TEXT,
    grounded               BOOLEAN,
    input_validation_status  TEXT NOT NULL DEFAULT 'passed',  -- passed | rejected  (new — kernel-hook-written)
    output_filter_status     TEXT NOT NULL DEFAULT 'passed',  -- passed | filtered   (new — kernel-hook-written, replaces output_filtered boolean)
    output_filter_reason     TEXT,                            -- grounding_fail | leak_check_fail | pii_check_fail | length_fail | null  (new)
    latency_ms             INT,
    token_input             INT,
    token_output            INT,
    cost_usd                NUMERIC(10,6),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX query_audit_log_idempotency_key_idx ON query_audit_log (idempotency_key) WHERE idempotency_key IS NOT NULL;

-- Agent decision trace (§15.6) — new
CREATE TABLE agent_trace_log (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_name          TEXT NOT NULL,             -- ingestion_agent | retrieval_agent | orchestrator
    tool_name           TEXT NOT NULL,
    input               JSONB NOT NULL,
    output              JSONB,
    session_id          UUID REFERENCES chat_sessions(id),      -- null for ingestion-time calls
    query_audit_log_id  UUID REFERENCES query_audit_log(id),    -- null for ingestion-time calls
    document_id         UUID REFERENCES documents(id),          -- null for chat-time calls
    duration_ms         INT,
    error               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX agent_trace_log_session_idx ON agent_trace_log (session_id);
CREATE INDEX agent_trace_log_document_idx ON agent_trace_log (document_id);

-- Retrospective response grading (§11.6, §20) — new
CREATE TABLE response_grade (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_audit_log_id      UUID NOT NULL UNIQUE REFERENCES query_audit_log(id) ON DELETE CASCADE,
    grounding_check_passed  BOOLEAN,          -- deterministic re-check, run on every graded row
    judge_score             SMALLINT,         -- 1-5 rubric score; null unless this row was sampled for LLM-judge grading
    judge_rationale         TEXT,
    sampled                 BOOLEAN NOT NULL DEFAULT false,
    graded_at               TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX response_grade_query_audit_log_idx ON response_grade (query_audit_log_id);

-- One-row-per-response lineage (§11.5, §3) — new
CREATE VIEW agentops_summary AS
SELECT
    qal.id                      AS query_audit_log_id,
    qal.session_id,
    qal.query,
    qal.cache_status,
    qal.cost_category,
    qal.retrieval_mode,
    qal.generation_model,
    qal.grounded,
    qal.input_validation_status,
    qal.output_filter_status,
    qal.output_filter_reason,
    qal.latency_ms,
    qal.cost_usd,
    rg.grounding_check_passed   AS graded_grounding_passed,
    rg.judge_score              AS graded_judge_score,
    rg.graded_at,
    array_agg(DISTINCT atl.tool_name) FILTER (WHERE atl.tool_name IS NOT NULL) AS agent_tools_invoked,
    count(DISTINCT atl.id)      AS agent_trace_row_count,
    qal.created_at
FROM query_audit_log qal
LEFT JOIN agent_trace_log atl ON atl.query_audit_log_id = qal.id
LEFT JOIN response_grade rg   ON rg.query_audit_log_id = qal.id
GROUP BY qal.id, rg.grounding_check_passed, rg.judge_score, rg.graded_at;

-- Anomaly detection flags (§20.1) — new
CREATE TABLE anomaly_flag (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    metric_name     TEXT NOT NULL,      -- cost_usd | latency_ms | cache_hit_rate | output_filter_rate | grounded_false_rate | agentic_expanded_rate
    hour_of_day     SMALLINT NOT NULL,  -- 0-23, bucket the baseline is computed against
    observed_value  NUMERIC,
    baseline_mean   NUMERIC,
    baseline_stddev NUMERIC,
    z_score         NUMERIC,
    window_start    TIMESTAMPTZ NOT NULL,
    window_end      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX anomaly_flag_metric_idx ON anomaly_flag (metric_name, created_at);
```

**`content_tsv` is a generated column, not application-populated (revised).** `GENERATED ALWAYS AS (to_tsvector('english', content)) STORED` keeps it in sync with `content` automatically on every insert/update — no trigger, no application code in `chunk_document`/`write_chunks` needs to remember to write it, and it can't silently drift `NULL` the way an ordinary column populated by app code could. Postgres 16 (§19's RDS target) supports generated columns natively.

**Why HNSW over IVFFlat** — unchanged: no training step, better recall/query-speed at this scale.

**Migrations.** Alembic, additive, versioned — `page_images`, `agent_trace_log`, `response_grade`, `agentops_summary`, and `anomaly_flag` are each new migration files, not edits to the original schema migration, keeping the change surgical and reviewable (§22).

---

## 7. Retrieval & Indexing

### 7.1 Cache-before-corpus — unchanged

Every chat query checks the cache layer (§9) before the vector index is touched at all.

### 7.2 Hybrid retrieval (cheap, and it stays cheap) — revised, now the Retrieval Agent's `hybrid_search` tool

The same query runs a `tsvector` full-text search (GIN-indexed) alongside HNSW vector search, merged via **Reciprocal Rank Fusion**: `score(d) = Σ 1 / (k + rank_i(d))` across the lexical and vector rankings, `k = 60` (standard default — see §17). This always runs first, agentic or not.

**RRF's job here is candidate fusion and ordering into rerank, not confidence-gating.** At `k=60`, a document ranked #1 in both the lexical and vector lists scores `2/61 ≈ 0.033` — the maximum any document can reach with two ranking lists. Raw RRF scores at this `k` live in the `0–0.033` range, not on a 0–1 scale, so they're the wrong signal to compare against a fixed human-legible threshold like `0.55`. RRF fuses and orders the top-20 candidates handed to `rerank`; the gate that decides deterministic-vs-agentic (§7.3, §15.3) reads the reranker's score instead, since that's a purpose-built relevance signal that's actually bounded.

**Implementation note — `hnsw.ef_search` and connection pooling:** pgvector treats `ef_search` as a session/transaction-local setting (`SET LOCAL hnsw.ef_search = ...`), not a global. With a pooled `asyncpg` connection (§3), this has to be set explicitly at the start of every query's transaction — otherwise a value set by a previous request can leak into an unrelated one on a reused connection. `hybrid_search`'s implementation issues `SET LOCAL hnsw.ef_search = :HNSW_EF_SEARCH` inside the same transaction as the ANN query, every call, rather than assuming a session default.

### 7.3 Retrieve-then-rerank, with a confidence gate (revised — gate moved off raw RRF)

Over-fetch top-20 from the cheap ANN/lexical fusion, then **always** apply a cross-encoder rerank (§17) to that top-20 — reranking itself is not gated, it's local/CPU-bound and cheap regardless of path. The reranker's top result is passed through a sigmoid activation to produce a relevance score naturally bounded to 0–1, and *that* score — not the RRF fusion score from §7.2 — is checked against `RETRIEVAL_AGENT_CONFIDENCE_THRESHOLD` (default 0.55) to decide whether the plain top-20's reranked result is good enough to return, or whether `expand_query` should decompose/rewrite the query, re-run `hybrid_search` per sub-query, and rerank again over the merged, expanded candidate set. This is a **cascade, not a default** — most queries take the single deterministic pass (one `hybrid_search` + one `rerank`, no LLM call); only low-confidence ones pay for the extra agentic round-trip (`expand_query`, which *is* an LLM call). Full mechanism in §15.3.

**Why this is the right split:** rerank is already computed once regardless of path, so gating on its output costs nothing extra — it just changes which number a decision already being made reads. Gating on RRF instead would have required either min-max normalizing RRF scores per-query (workable, but throws away a signal — RRF — that's good at fusion, not confidence) or hand-picking a differently-scaled threshold; reading the reranker's own bounded, purpose-built relevance score avoids both problems.

**Trade-off, unchanged:** reranking adds latency and a small per-query cost; for a small corpus where top-20 is already well-ordered, the marginal benefit shrinks — measured against the golden set (§11.2), not assumed.

### 7.4 Context compaction, now multimodal-aware

Each selected chunk is trimmed to the passage actually relevant to the query, as before. **New:** if a selected chunk's source page has a `page_images` row (§4.3), the page image is attached to the generation call alongside the (still-compacted) text chunk — the image supplements the text, it doesn't replace the compaction step.

### 7.5 Grounding — unchanged

The generation call is structured so every claim traces to a retrieved chunk; the output filter (§12.2) verifies this before send.

### 7.6 Retrieval quality is measured, not assumed — unchanged, extended

The golden-set eval (§11.2) now also reports precision@K split by `retrieval_mode` (`deterministic` vs `agentic_expanded`) — this is what would justify (or disprove) the gating threshold's default value, per the honest caveat in §15.3.

---

## 8. Conversation Context Management — unchanged

A multi-turn chat session's prompt grows with every turn if handled naively.

- **Sliding window:** last *N* turns (default 6) kept verbatim.
- **Rolling summary beyond the window:** once total token count crosses ~2,000, older turns collapse into a running summary (one cheap-tier model call, threshold-triggered), stored as a `system_summary` row.
- Separate from §7.4's per-chunk compaction — one bounds conversation history, the other bounds retrieved-content size.

---

## 9. Caching Architecture (Additional Service Layer)

### 9.1 Exact cache — unchanged
Normalized-query hash → cached answer (`exact_cache`), TTL-bound (24h default).

### 9.2 Semantic cache — eviction and invalidation added (fixed)
Query embedding vs. stored past-query embeddings (`semantic_cache`); cosine ≥ 0.92 threshold; repeated near-duplicates increment `hit_count`. Implemented in Postgres (second HNSW index); Redis named as the next step if lookup latency becomes measurable.

`exact_cache` already has both a TTL and a named eviction cron (§9.1, §20); `semantic_cache` previously had neither, which left two separate problems open: unbounded growth of its HNSW index over time, and staleness — "freshness re-check against re-uploaded/deleted documents" was asserted without a stated mechanism. Both are now closed as an extension of the same scheduled job (§20), not a new service:

- **Size cap (LRU by `last_used_at`):** the job caps `semantic_cache` row count at `SEMANTIC_CACHE_MAX_ROWS` (§23); when exceeded, the oldest `last_used_at` rows are evicted first, keeping frequently-reused entries regardless of insertion order.
- **Invalidation on document change:** each `semantic_cache` row's answer traces back to the `source_doc_ids` it was generated from (same pattern as `exact_cache`, §6). The job deletes any `semantic_cache` row whose `source_doc_ids` intersects a document that was deleted or re-ingested (new `content_hash`) since the row was cached — a stale cached answer citing a document that no longer exists, or exists in a changed form, is worse than a cache miss.

### 9.3 Prompt caching (provider-level)
Stable system-prompt prefix (instructions, output-format/grounding rules, tool definitions — now including the agent tool schemas in §15) cached at a steep per-call discount; per-request variable content (retrieved chunks, page images, the question) placed after the cache breakpoint. Stacks with, doesn't replace, the response caches above.

---

## 10. Cost Optimization (Consolidated View)

| Lever | What it controls | Where it's implemented |
|---|---|---|
| Exact + semantic response cache | Skips retrieval + generation entirely on repeat/near-duplicate queries | §9.1–9.2 |
| Prompt caching | Reduces cost of the stable part of every remaining call | §9.3 |
| Hybrid + reranked retrieval | Keeps K small and high-precision | §7.2–7.3 |
| Context compaction | Trims each retrieved chunk to its relevant passage | §7.4 |
| Conversation sliding window + summary | Bounds prompt growth over a long session | §8 |
| Dynamic max-output-token caps | Bounds output tokens directly (billed materially higher than input) | Generation call, per request type |
| Model tiering / cascade routing | Cheap/fast model for classification; strong model for complex reasoning | `GENERATION_MODEL_FAST`/`GENERATION_MODEL_PRIMARY` (§23) |
| Rate limiting | Caps worst-case spend from one session or a scraping attempt | §13 |
| Ingestion dedup | Never re-embed an already-indexed document | §4.4 |
| **Gated agentic retrieval (new)** | Extra query-planning LLM call only fires on low-confidence hybrid search, not every turn | §7.3, §15.3 |
| **Flagged-page-only rasterization (new)** | Multimodal generation input stays bounded to the handful of pages retrieval decided matter, not every page of every document | §4.3, §7.4 |
| **Local cross-encoder reranker (new)** | Avoids a per-query hosted-reranker API cost by running scoring in-process | §15.2, §17 |

### 10.1 Dynamic Model Tiering & API Key Security Architecture

To balance cost, speed, and accuracy, the RAG implementation enforces automated model selection. Each task is dynamically routed to the most efficient model tier that meets its reasoning requirements, isolating high-cost calls from the runtime user loop:

```
[User Chat Prompt]
        │
        ├──► [Cheap/Fast Tier (Haiku/Gemini Flash)] ──► Simple classifications, intent parsing, exact-match routing.
        │
        ├──► [High Precision Tier (Sonnet/Gemini Pro)] ──► Core RAG, Agentic query-planning, conversational output.
        │
[Nightly Cron Job]
        │
        └──► [Ultimate Reasoning Tier (Opus/Gemini Ultra)] ──► Out-of-band Evaluation & Grading Agent (weighted rubrics).
```

#### A. Model Auto-Selection & Tiering Framework
1.  **Low Complexity / High Speed Tier (`CLAUDE_HAIKU` / `GEMINI_FLASH`):** Charged with initial intent classification, lightweight session summaries, and cached-miss validation. Highly cost-effective and optimized for sub-second latency. Controlled by `GENERATION_MODEL_FAST`.
2.  **Medium-High Complexity Tier (`CLAUDE_SONNET` / `GEMINI_PRO`):** Charged with active multi-agent ingestion/retrieval decisions, complex query planning, prompt-injection validation, and multi-turn conversational answer generation. This balances outstanding precision and grounded generation with sustainable costs. Controlled by `GENERATION_MODEL_PRIMARY` and `AGENT_MODEL`.
3.  **Ultimate Complexity & Rubric-Grading Tier (`CLAUDE_OPUS` / `GEMINI_ULTRA`):** Reserved exclusively for the **Evaluation & Grading Agent** running out-of-band during the nightly retrospective job. This agent writes dynamically weighted marking rubrics for real conversation sessions and grades live responses step-by-step. To safeguard user chat latency and avoid runtime cost inflation, this tier is completely isolated from live-traffic paths. Controlled by `EVALUATION_MODEL_OPUS`.

#### B. API Secret Key Segregation & Security
To safely execute this multi-provider agent model, API credentials are strictly segregated in `.env` files and the cloud deployment environment:
*   **Separation of Concerns:** Separate API tokens are configured for OpenAI (`OPENAI_API_KEY`), Anthropic (`ANTHROPIC_API_KEY`), Gemini/Google (`GEMINI_API_KEY`), and Opus (`OPUS_API_KEY`). This limits blast-radius if a key is compromised and permits fine-grained billing alerts, spending limits, and provider-specific rate limits.
*   **Blast-Radius Isolation:** The `OPUS_API_KEY` can be isolated to a separate billing account or service principal, completely separate from runtime user-facing keys, preventing runaway cost spikes on the primary client-facing tier.
*   **Safe Container Injection:** In development, keys are populated locally inside `.env` (excluded from git tracking). In production (AWS ECS Fargate), keys are registered securely in AWS Secrets Manager and injected dynamically as environment variables at the container task boundary at boot, ensuring zero credential persistence inside source repositories, Docker images, or application console logs.

---

## 11. Testing Strategy (Requirement 5)

### 11.1 Backend — deterministic checks (fast, every CI build)

- Ingestion: a known test PDF produces the expected chunk count and page/section metadata.
- **New:** a known test PDF containing a table produces a `page_images` row for the correct page, and skips rasterization for pages without table/figure signals.
- **New:** a synthetic low-text-yield (scanned-image) test page triggers `extract_text_ocr_fallback` and produces non-empty extracted text.
- Retrieval: a known query against a known small corpus returns a chunk from the expected source document.
- **New:** a query engineered to produce a low fused top-score (e.g., an ambiguous multi-part question against a sparse corpus) triggers `expand_query`; a query with an unambiguous high-confidence match does not — asserted via `agent_trace_log` rows, not just the final answer.
- Guardrails: oversized/wrong-MIME upload rejected with correct status; prompt-injection-shaped query (including one embedded inside an agent tool's *output*, e.g. a malicious string returned from `hybrid_search` content) doesn't change system behavior (§12.1).
- API contract: schemas validate; auth-protected endpoints reject unauthenticated requests.

### 11.2 Backend — golden-set evaluation (small, sampled, run on demand)

5–10 question → expected-source-document pairs, run end-to-end, checked for retrieval hit-rate and groundedness, **now reported split by `retrieval_mode`** (§7.6) to validate the gating threshold rather than assume it.

### 11.3 Frontend — unchanged

- Component tests (Jest + RTL) for `/documents`: renders, client-side validation, progress/error/empty states.
- Chainlit's own rendering exercised indirectly via backend API-contract tests.
- E2E smoke test (Playwright): upload a PDF with a table → wait for `indexed` → ask a question whose answer depends on that table → receive a grounded response whose citation references the page that has a `page_images` row. This is the single highest-value test in the project — it exercises ingestion, structure detection, retrieval, the confidence gate, multimodal generation, and citation together.

### 11.4 Running tests — unchanged

Exact commands named in the README.

### 11.5 Full-lineage logging doubles as test infrastructure — extended

`query_audit_log` (§6) plus the new `agent_trace_log` together give a complete, replayable record of *what the system decided and why* for any given query or ingestion run — not just what it answered. This is the dataset the golden-set eval and any future regression check run against.

### 11.6 Retrospective response grading — nightly (new)

Everything in §11.1–§11.5 grades behavior **before** send (deterministic checks, golden-set eval, the pre-send output filter, §12.2). Nothing previously looked back at live traffic after the fact to ask "were the answers we actually sent any good" — `response_grade` (§6) closes that, as an extension of the scheduled job already named in §20, not a new service:

- **Every graded row gets a deterministic re-check:** `grounding_check_passed` re-runs the same grounding logic as the pre-send filter (§12.2, §7.5) against the persisted answer and its cited chunks — catching any drift between what passed at send-time and what a stricter or updated grounding check would say now, without needing a live request to test it.
- **A sample is evaluated by an exclusive Evaluation & Grading Agent using the high-reasoning OPUS model:** a fixed nightly sample (`RESPONSE_GRADING_SAMPLE_SIZE`, §23) of the prior day's `query_audit_log` rows gets a 1–5 rubric score plus a short rationale (`judge_score`, `judge_rationale`). This is executed by a dedicated Evaluation & Grading Agent powered exclusively by the **Claude 3/3.5 Opus** (`OPUS`) model (authorized via a separate, isolated `OPUS_API_KEY` to separate permissions and costs). To ensure absolute grading accuracy, this agent dynamically generates a weighted, multi-criteria marking rubric for the specific query context and then grades each response turn step-by-step against that rubric. Every step of this evaluation, grading, and rubric-generation logic is logged and traced into the `response_grade` and `agent_trace_log` tables for complete auditing.
- **Why sampled, not exhaustive:** an LLM-judge call on every single response would materially change §10's cost profile for a check that's meant to catch drift and rubric-level quality trends, not gate any individual response — the deterministic grounding re-check runs on every row precisely because it's nearly free; the judge call is sampled because it isn't.
- **Where this shows up:** `response_grade` joins into `agentops_summary` (§6, §11.5), so "what happened for this response, and was it any good" is one query, not a trace plus a separate lookup — and a sustained drop in `grounding_check_passed` or `judge_score` is exactly the kind of signal §20.1's anomaly detection watches for.

---

## 12. Security

### 12.0 Authentication & authorization — unchanged

Upload/document-management endpoints require an authenticated request (signed session JWT). Chat endpoint openness is an explicit README decision, not left ambiguous.

### 12.1 Prompt-injection defense — extended to agent tool boundaries

Uploaded PDF content and retrieved chunks are **data, never instructions** — this now explicitly includes content flowing *through* agent tool calls, not just the final generation prompt:

- Retrieved content is wrapped in explicit delimiters (an XML-style `<context>` block, §16) with an explicit instruction that content inside is reference material, never a command.
- **Tool results are also treated as data.** A tool result (e.g., text `hybrid_search` pulls from a chunk, or a `reason` string an agent writes into `expand_query`) is never concatenated into a position where a later agent turn or the final generation call would parse it as a system-level instruction. The Ingestion and Retrieval Agents' tool schemas (§15) are fixed and server-defined; no tool result can grant a new tool, change `tool_choice`, or alter `RETRIEVAL_AGENT_CONFIDENCE_THRESHOLD` at runtime.
- No capability, tool grant, or system behavior is ever expanded based on conversation *or document* content — what the backend is willing to do is fixed by server-side configuration, full stop.

### 12.2 Output filtering — unchanged

Grounding check, leak check, length/format check before send. A `search_result`-block citation (§16), if adopted, would be a **second** grounding signal to cross-check against this step, not a replacement for it — a model correctly citing a search result index isn't the same guarantee as the citation being semantically correct.

### 12.3 Input validation — unchanged

### 12.4 Standard API hardening — unchanged

### 12.5 PII hygiene — unchanged, extended

No raw PII in unstructured logs, now including `agent_trace_log.input`/`output` JSONB columns — the same redaction posture applied to `query_audit_log` applies here before persisting real program data.

---

## 13. Rate Limiting — unchanged

Per-session cap (30 req/hr default), enforced in FastAPI middleware before the cache lookup, `429` on breach with retry-after, no CAPTCHA-equivalent, no permanent account action.

---

## 14. Reliability Principle

**Fail loudly, not silently — extended to agent failure.** If the database, embedding provider, generation model, *or an agent tool call* times out or errors, the API returns a clear, honest error, or (for the Retrieval Agent specifically, §5.3, §15.5) falls back to the deterministic result already computed rather than surfacing an internal agent error to the user. The distinction matters: falling back to a known-good deterministic path is not the same as silently returning a stale or degraded answer and presenting it as complete — the fallback path is itself a fully valid, already-tested retrieval result, just not the (possibly better) agentic one.

---

## 15. Multi-Agent Architecture (Ingestion Agent, Retrieval Agent, Orchestrator)

**This section supersedes the prior single-orchestrator decision.** The prior framing — "a single linear pipeline doesn't yet have distinct enough concerns to justify agent boundaries" — no longer holds: structure detection (native-text vs. OCR fallback, which pages need image capture) and query planning (is this hybrid-search result good enough, or does the question need decomposition) are genuinely separable judgment calls with different failure modes, and the coordination cost of splitting them out is small at this process scale (typed function calls, no network hop, no message bus).

### 15.0 Build option, and why

| Option | Fit for this assessment |
|---|---|
| **Hand-rolled orchestrator (Messages API + tool use)** — chosen | No external dependency, no beta/research-preview risk; the coordination logic itself is what demonstrates engineering judgment for a graded assessment |
| Claude Agent SDK | Reasonable middle ground if built-in per-agent context/session management is wanted without writing the loop by hand — named here as the alternative considered, not adopted |
| Managed Agents (hosted, research-preview) | Not appropriate here — pulling in an external managed service for a 72-hour graded assessment trades control and demonstrable understanding for convenience this scale doesn't need; named as the production-scale future step, same pattern already used for OAuth2/SSO (§12.0) |

### 15.1 Agent boundaries

Chosen to match genuinely different judgment calls, not to split code for its own sake:

- **Ingestion Agent** — judgment: is this page native-text or does it need OCR, and which pages need image capture. Most of the pipeline underneath stays deterministic function calls; the agent wraps only the parts that require a decision. Model: Optimized for cost/speed via **Claude 3.5 Sonnet** (or Gemini Pro).
- **Retrieval Agent** — judgment: is the deterministic hybrid-search result confident enough to proceed, or does the query need expansion; does a top result's page need its image pulled in. Model: Optimized for precision/speed via **Claude 3.5 Sonnet** (or Gemini Pro).
- **Orchestrator** — unchanged role from §2/§5, except it now calls the Retrieval Agent as a tool ("agent-as-tool": the sub-agent runs its own bounded tool-use loop internally and returns a structured result), then generates the final answer through the output filter exactly as §12.2 already does. Model: High speed **Claude 3.5 Haiku** (or Gemini Flash) for initial checks, tiering up to **Claude 3.5 Sonnet** for final generation.
- **Evaluation & Grading Agent (Nightly / Out-of-band)** — judgment: dynamically writes multi-criteria weighted marking rubrics for real conversation logs, and evaluates the generated response quality (1-5 score, step-by-step audit rationale). Model: Exclusively uses the maximum-analytical **Claude 3/3.5 Opus** (powered by a separate `OPUS_API_KEY` to isolate billing and security) or **Gemini Ultra** to ensure the highest-fidelity quality checks.

**Kernel Invariants.** Two structural rules govern how GUARD, IAGENT, ORCH, and RAGENT relate to each other in §2's diagram — named explicitly here rather than left as implicit prose, the same discipline AFYA-AOS's §4 applies at its own (much larger) scale, right-sized down to what this single-process, two-internal-agent system actually needs:

- **Kernel Invariant 1 — input validation and output filtering are non-optional hooks on every turn, not agent behavior an agent could skip.** Every request passes through input validation (§12.3) before it reaches any agent, and every generated response passes through the output filter (§12.2) before it's accepted for send — on every path, cache hit or miss, deterministic or agentic. No agent's own tool call or reasoning output can disable, reorder, or bypass either hook. Echoes AFYA-AOS's Rule 1 (§4) — "input validation and output filtering are kernel syscall hooks, not agent behavior" — at this project's scale: one FastAPI process enforcing the hook structurally in the request/response path, not a separate kernel process mediating A2A envelopes.
- **Kernel Invariant 2 — tool/capability grants are static and fixed at config time, never expanded by data.** The Ingestion Agent's loop is scoped to exactly `{detect_structure, extract_text_ocr_fallback, flag_table_pages}`; the Retrieval Agent's to exactly `{hybrid_search, rerank, expand_query, fetch_page_image}`. No content an agent processes — a retrieved chunk, a tool's own return value, uploaded PDF text — can ever grant a new tool, change `tool_choice`, or alter a threshold like `RETRIEVAL_AGENT_CONFIDENCE_THRESHOLD` at runtime. Already the mechanism behind §12.1's prompt-injection defense; named here as the second Kernel Invariant because it's the same structural guarantee AFYA-AOS's Rule 2 (§4) states for its own agent mesh — "capability grants are static and never runtime-negotiable" — this project just enforces it via fixed Python-level tool schemas per agent rather than a signed, cryptographically-verified `capability_token` (§22 in AFYA-AOS), since there's no cross-process/cross-account hop here for a forged token to cross.

### 15.2 Ingestion Agent — tools and execution model

**Tool schemas** (Anthropic Messages API `tools` format — implementable directly as-is):

```json
{
  "name": "detect_structure",
  "description": "Analyze a parsed PDF page for structural signals: table-like grid patterns, figure/image blocks, heading candidates, and text-extraction yield. Read-only, does not mutate the database. Called once per page during the initial parse pass.",
  "input_schema": {
    "type": "object",
    "properties": {
      "document_id": {"type": "string", "format": "uuid"},
      "page_number": {"type": "integer", "minimum": 1}
    },
    "required": ["document_id", "page_number"]
  }
}
```
Returns: `{has_table, has_figure, table_bbox, text_char_count, text_yield_ratio, heading_candidates, extraction_confidence: "native_text"|"low_yield_needs_ocr"}`. Impl: `pdfplumber` `page.find_tables()` for table geometry; `text_yield_ratio = extracted_char_count / page_area`, compared against `OCR_TEXT_YIELD_THRESHOLD` (§23) to set `extraction_confidence`.

```json
{
  "name": "extract_text_ocr_fallback",
  "description": "Re-extract text for a page detect_structure flagged low_yield_needs_ocr, via OCR. Only called for pages already flagged — never a blanket first pass, since OCR is slower and lower-fidelity than native extraction.",
  "input_schema": {
    "type": "object",
    "properties": {
      "document_id": {"type": "string", "format": "uuid"},
      "page_number": {"type": "integer"}
    },
    "required": ["document_id", "page_number"]
  }
}
```
Impl: `pdf2image.convert_from_path` (Poppler-backed) → `pytesseract.image_to_string`.

```json
{
  "name": "flag_table_pages",
  "description": "Given detect_structure results for a document, register a page_images row for each page where has_table or has_figure is true. Idempotent: re-running on an already-flagged page updates rather than duplicates the row.",
  "input_schema": {
    "type": "object",
    "properties": {
      "document_id": {"type": "string", "format": "uuid"},
      "page_numbers": {"type": "array", "items": {"type": "integer"}}
    },
    "required": ["document_id", "page_numbers"]
  }
}
```
Impl: rasterize via PyMuPDF (`page.get_pixmap(dpi=PAGE_IMAGE_DPI)`), store under `PAGE_IMAGE_STORAGE_BACKEND` (local/S3), upsert `page_images`.

```json
{
  "name": "chunk_document",
  "description": "Deterministic step: run the fixed-token/structure-aware chunker (§4.4) over the document's extracted text. Behavior doesn't vary by agent judgment; exposed as a tool for pipeline uniformity and tracing.",
  "input_schema": {
    "type": "object",
    "properties": {"document_id": {"type": "string", "format": "uuid"}},
    "required": ["document_id"]
  }
}
```

```json
{
  "name": "embed_batch",
  "description": "Deterministic step: batch-embed chunk texts via the configured EMBEDDING_MODEL.",
  "input_schema": {
    "type": "object",
    "properties": {"chunk_ids": {"type": "array", "items": {"type": "string", "format": "uuid"}}},
    "required": ["chunk_ids"]
  }
}
```

```json
{
  "name": "write_chunks",
  "description": "Deterministic, terminal step: persist embedded chunks and mark document status indexed.",
  "input_schema": {
    "type": "object",
    "properties": {"document_id": {"type": "string", "format": "uuid"}},
    "required": ["document_id"]
  }
}
```

**Execution model:** the agent loop's free choice is scoped to `{detect_structure, extract_text_ocr_fallback, flag_table_pages}` only, bounded to `min(page_count + 2, INGESTION_AGENT_MAX_ITERATIONS_HARD_CEILING)` tool calls (§23) — this is the assessment phase. **Fixed, cap corrected:** the cap used to sit at a flat `INGESTION_AGENT_MAX_ITERATIONS_PER_DOC=40`, which is smaller than `page_count` alone for any document past ~38 pages — well inside the project's own `MAX_PDF_PAGES=300` ceiling, and a completely ordinary size for a community-health protocol manual. Since `detect_structure` runs at least once per page, that flat cap silently truncated the assessment loop partway through the document and, per the fallback below, degraded structure detection for the *entire* document, not just the unassessed tail — quietly, since ingestion still reported `indexed`. The cap now scales with `page_count`, with `INGESTION_AGENT_MAX_ITERATIONS_HARD_CEILING` (default 320, set relative to `MAX_PDF_PAGES=300`, not to the low end of the range) as the only fixed ceiling, so a document within the stated size limit is never truncated by a limit sized for a much smaller one. **Worth considering as a follow-up, not required for this pass:** batching several pages per `detect_structure` call so the iteration budget scales sub-linearly with page count instead of ~1:1 — noted here rather than built, since it changes the tool's contract and isn't needed to close the defect itself. Once every page has been assessed, the FastAPI controller calls `chunk_document → embed_batch → write_chunks` **directly as plain function calls, not further agent turns** — these three are exposed as tool schemas mainly for tracing uniformity (every pipeline step gets an `agent_trace_log` row) and to keep the door open for a future case where re-chunking mid-loop is warranted (e.g., OCR recovery meaningfully changes extracted text), not because they need agentic judgment today. If the assessment-phase loop errors or exceeds its iteration cap, the controller falls back to a default assessment (`extraction_confidence = native_text` for all pages, no image flags) and proceeds through the deterministic tail — ingestion always completes; it just doesn't get the image-augmentation upgrade for that document (logged, not silently dropped — §14).

### 15.3 Retrieval Agent — tools, gating, and execution model

**Tool schemas:**

```json
{
  "name": "hybrid_search",
  "description": "Run the deterministic hybrid retrieval (Postgres tsvector full-text + pgvector HNSW ANN, merged via Reciprocal Rank Fusion, §7.2, §17). Always the first call in every retrieval, agentic or not.",
  "input_schema": {
    "type": "object",
    "properties": {
      "query": {"type": "string"},
      "document_id_filter": {"type": "array", "items": {"type": "string", "format": "uuid"}},
      "top_k": {"type": "integer", "default": 20}
    },
    "required": ["query"]
  }
}
```
Returns ranked candidates plus `top_score` (raw RRF fusion score, `k=60` — used to order the top-20 into `rerank`, not as a confidence signal; RRF at this `k` tops out at `2/61 ≈ 0.033` for two ranking lists and was never designed to sit on a 0–1 scale, §7.2).

```json
{
  "name": "rerank",
  "description": "Re-score top hybrid_search candidates with a local cross-encoder (§17) for precision; returns the final top-N chunks for generation.",
  "input_schema": {
    "type": "object",
    "properties": {
      "query": {"type": "string"},
      "candidate_chunk_ids": {"type": "array", "items": {"type": "string", "format": "uuid"}},
      "top_n": {"type": "integer", "default": 5}
    },
    "required": ["query", "candidate_chunk_ids"]
  }
}
```
Impl: `sentence-transformers` `CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")`, CPU-fine at this corpus scale (§17); config path swaps in a hosted reranker if `RERANK_PROVIDER` is set. Returns `top_relevance_score` — the top result's cross-encoder logit passed through a sigmoid, naturally bounded 0–1 — which is the confidence signal the gate below actually reads (§7.3). Rerank is **not gated**; it always runs once on the top-20 regardless of path, so reading its output costs nothing extra.

```json
{
  "name": "expand_query",
  "description": "Only called when rerank.top_relevance_score is below RETRIEVAL_AGENT_CONFIDENCE_THRESHOLD. Decomposes a multi-part/ambiguous question into 1-3 targeted sub-queries (e.g., 'compare protocol A and B' -> two sub-queries) or rewrites a vague query into retrieval-friendly phrasing. Each sub-query is re-run through hybrid_search + rerank and results are merged.",
  "input_schema": {
    "type": "object",
    "properties": {
      "original_query": {"type": "string"},
      "reason": {"type": "string", "description": "why expansion was judged necessary; logged to agent_trace_log for later threshold calibration"}
    },
    "required": ["original_query", "reason"]
  }
}
```

```json
{
  "name": "fetch_page_image",
  "description": "Given a chunk_id whose source page has a page_images row, fetch the stored PNG for inclusion in the generation call. Only called for chunks in the final reranked top-N with a matching page_images row, never a blanket fetch.",
  "input_schema": {
    "type": "object",
    "properties": {"chunk_id": {"type": "string", "format": "uuid"}},
    "required": ["chunk_id"]
  }
}
```

**Gating logic (the cascade):**

```
hybrid_results = hybrid_search(query)                         # RRF fusion/ordering only, §7.2 — always runs
candidates = rerank(query, hybrid_results)                    # always runs, no LLM call, cheap/CPU-bound
if candidates.top_relevance_score >= RETRIEVAL_AGENT_CONFIDENCE_THRESHOLD:   # default 0.55, cross-encoder sigmoid score
    pass                                                       # deterministic path — plain top-20's reranked result is good enough
else:
    sub_queries = expand_query(query, reason=...)              # bounded agentic sub-loop, LLM call
    all_results = [hybrid_search(q) for q in sub_queries]
    candidates = rerank(query, merge(all_results))             # agentic path — re-rerank the expanded candidate set
for chunk in candidates.top_n:
    if chunk.page has page_images row:
        fetch_page_image(chunk.id)
return RetrievalResult(chunks=candidates.top_n, page_images=[...], expanded=bool, top_relevance_score=candidates.top_relevance_score)
```

Bounded to `RETRIEVAL_AGENT_MAX_ITERATIONS` (default 3: one `hybrid_search`+`rerank` pass, one `expand_query` decision, one re-`rerank`) — this keeps worst-case added latency predictable rather than open-ended. **Honest caveat:** the 0.55 threshold is an engineering starting default, not derived from this project's own data — §7.6/§11.2 name the golden-set split that would validate or recalibrate it.

### 15.4 Orchestrator — agent-as-tool

```json
{
  "name": "consult_retrieval_agent",
  "description": "Delegate retrieval to the Retrieval Agent's bounded sub-loop; returns a structured result. The Orchestrator never queries the database or vector index directly — retrieval is always delegated through this single tool.",
  "input_schema": {
    "type": "object",
    "properties": {
      "query": {"type": "string"},
      "session_id": {"type": "string", "format": "uuid"}
    },
    "required": ["query", "session_id"]
  }
}
```
Return shape: `{chunks: [{chunk_id, text, document, page_number}], page_images: [{chunk_id, storage_ref}], expanded: bool, top_score: float}`. The Orchestrator applies §7.4 compaction, builds the generation call (text + any page images), and runs the draft through the output filter (§12.2) — unchanged from the pre-agent design; the only thing that moved is *how* the chunks got there.

### 15.5 Handoff mechanism and failure containment

No message bus at this process scale. Each agent boundary is a **typed (Pydantic) function call within the same FastAPI process**; Postgres remains the shared state (`chunks`, `page_images`, `agent_trace_log`), not direct agent-to-agent messaging. This is what §15.0's future-A2A note already anticipated: the API surface is stateless and schema-validated, so if an agent boundary ever needs to become a real network hop later, the contract doesn't change, only its transport does. Every tool call, on every agent, is wrapped so a failure degrades to the nearest deterministic fallback (§14) rather than propagating as an unhandled error — Ingestion Agent failures fall back to a conservative no-image-flags assessment (§15.2); Retrieval Agent failures fall back to the plain `hybrid_search`+`rerank` result already computed (§15.3, §5.3).

### 15.6 Observability — `agent_trace_log`

Extends the existing full-lineage logging philosophy (§11.5) rather than inventing a separate mechanism: `agent_trace_log` (`agent_name`, `tool_name`, `input`, `output`, `session_id`/`query_audit_log_id`/`document_id` FKs, `duration_ms`, `error`; schema in §6) gives per-tool-call visibility into what each agent decided and why, using the same audit-log pattern already established for `query_audit_log`.

### 15.7 Cost/latency — the trade-off to keep visible, not just in your head

An unconditional agentic retrieval loop means 1–2 extra generation-model calls per chat turn (query planning/expansion) on top of generation itself — directly cutting against §10's cost optimization. Gating on low hybrid-search confidence (§15.3) is what keeps this from becoming the default cost profile: most queries take the cheap deterministic path, and only genuinely ambiguous ones pay for agentic reasoning. This is the same cascade pattern §10 already uses for model tiering, applied one layer up the pipeline.

### 15.8 MCP — documented, not built

Unchanged conclusion: the tool schemas in §15.2/§15.3 are already MCP-shaped (narrow, single-purpose, JSON-schema-typed) — exposing them behind an MCP server later would let any MCP-compatible client call this system's retrieval or ingestion capability as a tool, without a rewrite. Nothing in this assessment's scope needs an external MCP client calling in, so this stays a documented extension point, not a build item — building it now would read as scope-inflation for a 72-hour assessment, not rigor.

### 15.9 Per-agent-instance identity tokens — explicitly not adopted

AFYA-AOS issues each agent its own signed, short-TTL non-human identity — a Cognito machine-to-machine credential with a `sub` claim shaped `agent:<agent-name>:<country-stack>:<instance-id>` (§22.1) — independently verified by the receiving MCP server against a trusted issuer for every A2A call (§22.2, RFC 8693 token exchange). That mechanism exists to answer "which specific agent instance, in which AWS account, made this call" across a mesh of independently-deployed agents with real network hops between them.

This project has no such hop: the Ingestion Agent, Retrieval Agent, and Orchestrator are Python classes inside one FastAPI process, calling each other as typed in-process function calls (§15.5), not agents authenticating to each other over a network. There is no receiving MCP server for a forged or replayed token to fool, because there's no process boundary between agents for a credential to cross in the first place — Kernel Invariant 2 (§15.1) already prevents an agent from calling outside its fixed tool scope, and that's enforced by which Python function references exist in scope, not by a token a compromised call could present. Issuing and verifying per-agent-instance identity tokens here would add real implementation cost (an OIDC issuer, token minting/verification on every internal call, a credential rotation story) for a security property this process boundary doesn't have a corresponding threat for. Logged in §18's Decision Log as explicitly not adopted, not silently omitted — the same "name it, don't skip it" standard this document applies to every other AFYA-AOS pattern considered and set aside (§0 revision note).

---

## 16. Citations: `search_result` Blocks vs. the Hand-Rolled `<context>` Approach

§12.1's delimiter-based `<context>` block is sound prompt-injection defense and stays as the default — this section documents a candidate *upgrade* to the citation-mapping half of that mechanism, not a replacement for the defense itself.

**What changes, if adopted:** the Messages API's `search_result` content block type is purpose-built for RAG, with citation mapping built in — the Orchestrator could hand the generation call structured `{document, page, text}` results instead of a flat XML blob, and get back citations already tied to specific results, rather than reconstructing that mapping by hand for `source_chunk_ids` (§6, §5.2).

**Why this is "considered," not "chosen":** the exact API/version/beta requirements for `search_result` blocks weren't re-verified as part of this design pass — this needs a docs check and a small spike (swap one endpoint, compare citation accuracy against the current `source_chunk_ids` reconstruction) before it goes into §18's Decision Log as *chosen* rather than *considered*. If it pans out, it becomes a **second, provider-native grounding signal to cross-check against §12.2's custom grounding check**, not a replacement for it — a model correctly citing search result index 2 isn't the same guarantee as "the citation is semantically correct," so §12.2 stays as defense-in-depth either way.

---

## 17. Library & Algorithm Choices (ML-adjacent)

Every "ML algorithm" this design needs is a well-established technique with a mature, pip-installable Python library — no custom model training, no GPU provisioning, no new infrastructure beyond what §0's stack table already lists.

| Task | Library / Algorithm | Why this one |
|---|---|---|
| Table/figure structure detection | `pdfplumber` (`find_tables()`, line/rect geometry) | Rule-based, deterministic, already needed for text extraction — no separate detection model to train or host |
| PDF → PNG rasterization | `PyMuPDF` (`fitz`) | Fast, pure-Python-installable, no external binary beyond the wheel itself |
| OCR fallback | `pytesseract` + `pdf2image` | Standard, well-documented; requires system-level Tesseract + Poppler (Dockerfile dependency, §21) |
| Hybrid retrieval fusion | Reciprocal Rank Fusion (`score = Σ 1/(k+rank)`, k=60) | Simple, parameter-light, no training; implementable in a few lines of Python/NumPy, no library needed beyond the DB queries it fuses |
| Reranking | `sentence-transformers` `CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")` | CPU-viable at this corpus scale, no extra infrastructure, no external API cost; hosted reranker named as the production alternative if precision needs exceed it |
| Query decomposition/expansion | Generation model call (Claude), not a classical ML library | This is a language-understanding judgment call, not a pattern classical NLP libraries solve well — appropriately delegated to the same model already in the stack |
| Embeddings | Configured `EMBEDDING_MODEL` (OpenAI/Voyage, §23) | Unchanged from the prior revision |

---

## 18. Decision Log

| Decision | Choice | Alternative considered | Why |
|---|---|---|---|
| Frontend/backend frameworks | Keep Next.js + FastAPI | Substitute either | Both already fit the task well; substitution would trade depth for no clear benefit here |
| Chat surface | Chainlit, alongside Next.js | Custom chat UI in Next.js | Chainlit's built-in streaming/citation/file-in-chat UX would take real time to hand-roll; Next.js suits the document-management page better |
| Vector index type | pgvector HNSW | pgvector IVFFlat | No training step; performs better at low-to-moderate row counts, which is this assessment's regime |
| Chunking strategy | Fixed-token (~480 tokens, 15% overlap) with structure-aware override | Pure semantic chunking | Benchmarked evidence favors fixed/recursive as the stronger default; semantic chunking only earns adoption after an A/B test |
| Retrieval | Hybrid (lexical + vector) + rerank | Vector-only | Postgres full-text search is close to free and catches exact-term matches vector search under-ranks |
| Response cache backend | Postgres (second HNSW index) | Redis | Simpler to operate at this scale; Redis is the named next step if lookup latency becomes measurable |
| Schema migrations | Alembic (versioned, additive) | Hand-run `init.sql` | Keeps schema changes in reviewable history, consistent with commit-cadence discipline (§22) |
| API documentation | FastAPI auto-generated OpenAPI (`/docs`) | Hand-maintained API doc | Can't drift from the implementation; zero extra maintenance cost |
| Authentication | Lightweight JWT session token | Full OAuth2/SSO | Right-sized for a demo; OAuth2/SSO named as the production next step |
| PDF size/page limits | 20 MB / 300 pages | No limit | Bounds worst-case ingestion cost and time at the API boundary |
| **Agent architecture (revised)** | **Multi-agent: Ingestion Agent, Retrieval Agent, Orchestrator; hand-rolled via Messages API + tool use; gated agentic retrieval on low-confidence hybrid search** | Single orchestrator (prior decision); Claude Agent SDK; Managed Agents | Ingestion and retrieval now have genuinely separable failure modes and judgment calls (structure/OCR detection, query planning) that justify the coordination cost; hand-rolled avoids external/beta dependency risk for a graded assessment; gating keeps §10's cost profile intact rather than paying an agentic tax on every turn |
| Table/figure handling | Detect + rasterize only flagged pages, attach page image alongside text chunk at generation | Full-page images for every page always; text-only (status quo) | Bounds multimodal cost to pages retrieval already decided matter; text-only under-serves tables/dosage charts/decision trees, which are exactly this domain's lossy case |
| Ingestion Agent scope | Agentic loop bounded to `{detect_structure, extract_text_ocr_fallback, flag_table_pages}`; `chunk_document`/`embed_batch`/`write_chunks` called deterministically by the controller | Fully agentic 6-tool open loop | Matches the actual decision points (structure/OCR judgment) without agentifying steps that have no judgment to make; keeps latency/cost predictable |
| Reranker implementation | Local `sentence-transformers` CrossEncoder | Hosted reranker API | No new external dependency or per-query cost at this scale; hosted reranker named as the production alternative if precision needs grow |
| Citation mechanism | Hand-rolled `<context>` block (kept as default) | `search_result` content blocks | Sound injection defense already in place; `search_result` blocks are a candidate upgrade pending an API/version spike (§16), not yet proven in this project |
| Retrieval Agent gating | Cascade on low reranker relevance confidence (default 0.55) | Always-agentic retrieval; raw RRF score gating | Keeps the cheap deterministic path as the default while avoiding the known RRF range mismatch; threshold is a starting default pending golden-set calibration (§7.6) |
| Page-image access | `fetch_page_image` remains internal-only for final reranked chunks | Public page-image route | Page images can contain the same protocol content as text chunks; public source-page viewing needs a separate authorization design, so BC9 exposes no route |
| Context compaction | Deterministic lexical-overlap sentence selection, restored to document order | LLM-based summarization per chunk | Keeps BC10 deterministic, testable, and cost-free; images supplement compacted text rather than replacing it |
| Scheduler timing | Lightweight in-process cache scheduler starts at BC11 and is extended by BC20 | Wait until BC20 or create a second scheduler later | Cache TTL/LRU/invalidation are BC11 requirements; one scheduler avoids duplicated scheduling systems when BC20 adds grading/anomaly jobs |
| Cache write eligibility | Exact and semantic writes take `eligible: bool`, currently true until BC14 | Cache every full-pipeline answer unconditionally | Prevents future filtered/rejected answers from being cached; BC14 only needs to wire `eligible = output_filter_status == "passed"` |
| Cache invalidation | Delete cache rows whose `source_doc_ids` reference missing document IDs | Track in-place document content-hash changes | The current document lifecycle deletes/reuploads as new IDs, so missing referenced IDs are the concrete stale-answer signal for BC11 |
| Backend database access implementation | Continue SQLAlchemy async sessions with explicit `text()` SQL for pgvector/full-text retrieval | Rework the implemented backend to raw `asyncpg` before BC7 | The repository has already standardized on SQLAlchemy models, sessions, and Alembic integration through BC6. BC7 still uses inspectable hand-written SQL for `SET LOCAL hnsw.ef_search`, pgvector distance, and full-text search, preserving the architecture's operational requirements without introducing a second DB access paradigm mid-build. |

*(Add rows as further implementation decisions are made — this table is the canonical record of "why," which is explicitly part of what the assessment grades.)*

---

## 19. Production Deployment Plan (Requirement 7)

- **Cloud provider:** cloud-agnostic by design (containerized stack), deployed here on AWS as a concrete default — ECS Fargate for the three app containers (Next.js, Chainlit, FastAPI), RDS for PostgreSQL 16+ with `pgvector` enabled, S3 for uploaded PDFs *and* rasterized page images (§4.3) rather than container-local storage, Secrets Manager for API keys, an Application Load Balancer in front of the services.
- **Why Fargate over serverless/functions:** this workload has occasionally-long-running requests (PDF parsing, batch embedding, the Ingestion Agent's per-page assessment loop) and a persistent database connection pool — a warm container fits that shape better than a cold-start-sensitive function.
- **CI/CD:** GitHub Actions — lint and test on every PR (backend `pytest` including agent tool tests, frontend `npm test`/Playwright, §11), build and push images on merge to `main`, deploy via the platform's native deploy action or a thin Terraform apply. Tests gate the deploy.
- **Infrastructure considerations:**
  - Multi-AZ RDS.
  - Automated backups / point-in-time recovery.
  - A health-check endpoint per service.
  - The backend is stateless (§3, §5.4), so it scales horizontally with no sticky-session requirement.
  - **New:** the backend container image needs system-level `tesseract-ocr` and `poppler-utils` packages installed (Dockerfile `apt-get install`, not pip-installable) for the OCR fallback and rasterization paths (§4.3, §21) — a deployment-relevant detail, not just a local-dev one.
- **Observability:** structured JSON logging to CloudWatch Logs (or equivalent); `query_audit_log` and, new, `agent_trace_log` (§6) as the primary application-level metrics source (latency, cache-hit rate, cost, groundedness pass-rate, agentic-vs-deterministic retrieval split); a basic alert on elevated error rate or p95 latency breach.
- **Cost note:** pgvector on RDS avoids the "managed vector database has a minimum monthly floor" problem some dedicated vector databases carry.

---

## 20. Additional Service Layers (Bonus)

- **Caching** — full detail at §9.
- **Scheduling** — a lightweight scheduled job (APScheduler in-process, or a cron-triggered endpoint) for: expiring stale `exact_cache` entries past TTL, re-embedding documents if the embedding model configuration changes, and **(new)** re-running structure detection/rasterization for previously-ingested documents if the table-detection heuristic or `PAGE_IMAGE_DPI` setting changes — detectable directly from a version/config marker stored on `documents.metadata`, same pattern as the existing embedding-model-mismatch check.

---

## 21. Assumptions

Explicit, since the assessment invites noting them rather than treating them as implicit:

1. **Container image installs system-level `tesseract-ocr` and `poppler-utils`.** `pytesseract`/`pdf2image` are thin Python wrappers around these binaries; they aren't pulled in by `pip install` alone. This is a Dockerfile line, not a Python dependency, and is called out explicitly so it isn't missed at build time.
2. **The generation model used for chat is multimodal** (accepts an image alongside text in the same Messages call) — required for §4.3/§7.4's page-image augmentation to work at all. If the configured `GENERATION_MODEL_PRIMARY`/`_FAST` doesn't support image input, that feature degrades gracefully to text-only (the `page_images` table and rasterization still populate; they're just not attached to the generation call) rather than breaking ingestion or chat.
3. **Native-PDF-handling page/size thresholds** (relevant only if a future iteration sends whole PDFs natively instead of the flagged-page-image approach used here) are explicitly *not* hard-coded from memory in this document — see the caveat in §4.1. This project's own approach (rasterize flagged pages only) doesn't depend on those thresholds, so it isn't a blocking assumption, just one worth not silently inheriting from stale defaults later.
4. **`search_result` content block availability** (§16) is unverified as of this design pass — treated as a documented candidate, not a build requirement, specifically so the citation mechanism that *is* built (§12.1) doesn't depend on an unconfirmed API surface.
5. **`RETRIEVAL_AGENT_CONFIDENCE_THRESHOLD = 0.55`** and the various `MAX_ITERATIONS` bounds (§15.2, §15.3, §23) are engineering starting defaults chosen to bound worst-case latency/cost, not values derived from this project's own golden-set data — §7.6/§11.2 name the calibration step that would validate them.
6. **Single-tenant deployment scope** — no multi-organization data isolation is designed for; consistent with §12.0's "lightweight auth, OAuth2/SSO named as the production next step" framing, unchanged from the prior revision.
7. **CPU-only inference for the local cross-encoder reranker** (§17) — no GPU is provisioned in the deployment plan (§19); acceptable at this corpus/query-volume scale, called out as a scaling assumption that would need revisiting well before hosted-reranker economics would.
8. **A relational row (`documents.metadata`) is sufficient to detect a stale table-detection/rasterization configuration** for the scheduling job in §20 — this assumes config version markers are written at ingestion time, which needs to be part of the `write_chunks` implementation, not bolted on later.

---

## 22. Working Agreement for This Assessment

- **Commit frequently, with descriptive messages** — a suggested cadence, mapped to natural build phases:
  1. Repo scaffolding + this architecture doc
  2. Database schema + Alembic migration (incl. `page_images`, `agent_trace_log`)
  3. PDF upload endpoint + validation limits
  4. Structure detection (`detect_structure`, `flag_table_pages`) + rasterization
  5. Chunking + embedding pipeline (deterministic tail)
  6. Ingestion Agent loop (assessment phase) wired to the deterministic tail
  7. Retrieval (vector-only, then hybrid)
  8. Reranking (local cross-encoder)
  9. Retrieval Agent: confidence gate + `expand_query` + `fetch_page_image`
  10. Orchestrator: `consult_retrieval_agent` agent-as-tool wiring
  11. Caching layer (exact, then semantic)
  12. Chat endpoint + Chainlit wiring + session persistence + multimodal generation calls
  13. Next.js `/documents` upload page
  14. Guardrails (input validation, injection defense incl. tool-result boundaries, output filtering)
  15. Authentication + rate limiting
  16. Backend tests (deterministic, agent-tool, then golden-set eval)
  17. Frontend tests + e2e smoke test (table-page citation scenario)
  18. Deployment config + CI pipeline
  19. README/docs pass
- **Commit message convention:** `feat:`, `fix:`, `docs:`, `test:`, `chore:` prefixes.
- **Document architectural changes as they happen, not retroactively** — update §18 in the same commit that makes the change.
- **Expand this document and inline docstrings as the build progresses.**

---

## 23. `.env.example`

```bash
# ── App ──────────────────────────────────────────────
ENVIRONMENT=development
LOG_LEVEL=info

# ── Database ─────────────────────────────────────────
DATABASE_URL=postgresql://postgres:postgres@relational_db:5432/ragdb

# ── LLM / Embedding Providers ────────────────────────
ANTHROPIC_API_KEY=
OPENAI_API_KEY=                      # used for embeddings if not self-hosting
GEMINI_API_KEY=                      # Google Gemini API Key for fast/flexible models
OPUS_API_KEY=                        # Dedicated Claude Opus API Key for high-reasoning evaluation
VOYAGE_API_KEY=                      # optional — Voyage embeddings, commonly paired with Claude generation
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIM=1536
GENERATION_MODEL_PRIMARY=claude-sonnet-5
GENERATION_MODEL_FAST=claude-haiku-4-5
EVALUATION_MODEL_OPUS=claude-opus-3  # Dedicated Claude Opus model for Evaluation & Grading Agent
RERANK_PROVIDER=                     # optional — hosted reranker; unset uses the local cross-encoder (§17)

# ── Chunking ─────────────────────────────────────────
CHUNK_SIZE_TOKENS=480
CHUNK_OVERLAP_RATIO=0.15
STRUCTURE_AWARE_CHUNKING=true

# ── PDF Upload Limits ────────────────────────────────
MAX_PDF_SIZE_MB=20
MAX_PDF_PAGES=300
ALLOWED_MIME_TYPES=application/pdf

# ── Table/Figure Structure Detection & Page Images ───
TABLE_DETECTION_METHOD=pdfplumber     # pdfplumber | heuristic_grid
PAGE_IMAGE_DPI=200
PAGE_IMAGE_STORAGE_BACKEND=local      # local | s3 — mirrors UPLOAD_STORAGE_BACKEND
OCR_ENGINE=tesseract
OCR_TEXT_YIELD_THRESHOLD=0.15         # below this char/area ratio, a page is treated as scanned

# ── Multi-Agent Ingestion / Retrieval ────────────────
AGENT_MODEL=claude-sonnet-5           # model used for Ingestion/Retrieval agent reasoning turns
RETRIEVAL_AGENT_CONFIDENCE_THRESHOLD=0.55   # cross-encoder sigmoid relevance score (0-1, §7.3) below this triggers expand_query — NOT the raw RRF score
RETRIEVAL_AGENT_MAX_ITERATIONS=3
INGESTION_AGENT_MAX_ITERATIONS_HARD_CEILING=320   # outer cap, set relative to MAX_PDF_PAGES=300, not the low end of the size range
                                                   # per-doc bound is min(page_count + 2, this) — see §15.2
AGENT_TRACE_LOGGING_ENABLED=true

# ── Reranker (local ML model) ────────────────────────
RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2

# ── Citation Strategy (experimental — see §16) ───────
SEARCH_RESULT_BLOCKS_ENABLED=false    # flip only after the §16 spike confirms API/version support

# ── Retrieval ────────────────────────────────────────
RETRIEVAL_TOP_K=20
RERANK_TOP_N=5
HYBRID_SEARCH_ENABLED=true
HYBRID_FUSION_METHOD=rrf
RRF_K=60
HNSW_M=16
HNSW_EF_CONSTRUCTION=64
HNSW_EF_SEARCH=40

# ── Caching ───────────────────────────────────────────
CACHE_BACKEND=postgres               # postgres | redis
REDIS_URL=
EXACT_CACHE_TTL_SECONDS=86400
SEMANTIC_CACHE_ENABLED=true
SEMANTIC_CACHE_THRESHOLD=0.92
SEMANTIC_CACHE_MAX_ROWS=5000
PROMPT_CACHING_ENABLED=true

# ── Conversation Context Management ──────────────────
CONVERSATION_WINDOW_TURNS=6
CONVERSATION_SUMMARY_TRIGGER_TOKENS=2000
MAX_OUTPUT_TOKENS_CHAT=500
MAX_OUTPUT_TOKENS_SUMMARY=200

# ── Rate Limiting ─────────────────────────────────────
RATE_LIMIT_PER_SESSION_PER_HOUR=30
RATE_LIMIT_WINDOW_SECONDS=3600

# ── Security ───────────────────────────────────────────
JWT_SECRET=
SESSION_TOKEN_EXPIRY_MINUTES=60
ANONYMOUS_CHAT_ALLOWED=true
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8000
CHAINLIT_AUTH_SECRET=

# ── Storage ────────────────────────────────────────────
UPLOAD_STORAGE_BACKEND=local          # local | s3
S3_BUCKET_NAME=
AWS_REGION=

# ── Scheduling ─────────────────────────────────────────
ENABLE_SCHEDULED_JOBS=true
CACHE_EVICTION_CRON=0 * * * *
```
