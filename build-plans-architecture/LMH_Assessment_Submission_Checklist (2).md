# Last Mile Health — Senior Engineer, AI & Digital Health
## Skills Assessment: Pre-Submission Checklist

> Checklist audit status for this repository is tracked in `build-plans-architecture/SUBMISSION_CHECKLIST_STATUS.md`. Do not infer completion from unchecked original boxes; use that status document for the current pass/fail/partial notes.

> Use this as a final gate before you submit the forked repo link. Go through every box. Where a box can't be checked, either fix the gap or add an explicit note in the README under "Assumptions & Known Limitations" — the instructions explicitly allow assumptions as long as they're stated.

Stack assumed below (adjust section headers if you diverged): **FastAPI + pgvector + PostgreSQL + Next.js + Chainlit, Docker/docker-compose, `uv` for Python dependency management.**

---

## 0. ⭐ Priority Requirements — Verify These First

These three were called out for extra emphasis. Check them in detail, independent of the general pass below.

### A. Chat Interface — Chicago-style superscript citations
- [ ] Every claim in a generated answer that's grounded in a retrieved chunk carries an inline **superscript number** (`¹`, `²`, …) at the point in the sentence where that source is used
- [ ] Superscript numbers are **sequential per message** and map 1:1 to a reference list rendered below the answer
- [ ] Each reference entry follows **Chicago notes-bibliography style**: e.g. `1. Community Health Worker Training Manual, p. 14.` — italicized/styled document title + exact page number
- [ ] Page number is the **actual PDF page** the chunk came from — not a chunk index — which means page number must be captured and stored as chunk metadata at ingestion time (`app/services/ingestion.py`, `chunks.page_number` column)
- [ ] A sentence drawing on multiple chunks/pages shows multiple superscripts (`...shown in the data.¹ ²`) rather than one merged citation
- [ ] Citations are assembled from **retrieved chunk metadata**, never generated/guessed by the LLM — spot-check by manually opening the source PDF to the cited page and confirming the content matches
- [ ] No fabricated superscripts on ungrounded sentences (verify the grounding/no-citation edge case)
- [ ] Tested against a real multi-page, multi-section PDF — not a one-page fixture

### B. PDF Upload Page — fully responsive, autolayout
- [ ] Renders with **no horizontal scroll, no overlapping elements, no clipped controls** at: 375px (mobile), 768px (tablet portrait), 1024px (tablet landscape/small laptop), 1440px+ (desktop)
- [ ] Layout built with relative/fluid units (`%`, `rem`, `flex`, `grid`) rather than fixed pixel widths on main containers
- [ ] Drag-and-drop zone and file-picker button stay usable on mobile (tap target ≥44px)
- [ ] Upload progress and success/error feedback stay visible without horizontal scroll at the smallest tested width
- [ ] Ingested-document list reflows (stacks on mobile, grid on desktop) instead of being cut off
- [ ] Verified with browser dev-tools responsive mode (or real devices) at each breakpoint above — don't rely on "should be fine," actually check
- [ ] Same responsiveness pass applied to the chat page, since it shares layout primitives

### C. RAG Backend — scalable, secure, well-documented (demonstrated, not just asserted)
- [ ] **Scalable**: `async def` throughout the request path; DB access via an async connection pool, not one connection per request; ingestion/embedding runs as a background task (`BackgroundTasks`, Celery, or a queue) so upload requests aren't blocked on embedding generation; README has a "Scalability" subsection stating what's implemented vs. what's the documented next step under higher load
- [ ] **Secure**: upload restricted by MIME type + extension + size cap; no hardcoded secrets anywhere (grep the repo before submitting); parameterized queries/ORM only, zero raw string-interpolated SQL; CORS restricted to known origins in production config, not `*`; rate limiting on `/chat` and `/documents` noted at minimum as a documented next step if not implemented; README has a "Security" subsection
- [ ] **Well-documented**: FastAPI's auto-generated `/docs` (OpenAPI) is complete — every route has a summary, every request/response model has field descriptions; non-obvious logic (chunking strategy, prompt construction, retrieval scoring) has inline comments explaining *why*; README architecture section walks through ingestion → retrieval → generation end to end

---

## 1. Repository Root

| File | Required contents | ✅ |
|---|---|---|
| `README.md` | Project overview, architecture summary/diagram, local run instructions, test instructions, deployment plan, assumptions, trade-offs | [ ] |
| `.env.example` | Every env var used by backend, frontend, Chainlit, and Postgres — no real secrets, placeholder values only | [ ] |
| `.gitignore` | `.env`, `__pycache__/`, `node_modules/`, `.next/`, `*.pyc`, `.venv/`, `uv.lock` (only exclude if you intentionally don't want it committed — usually you DO want `uv.lock` committed for reproducibility), Docker volumes, DB data dirs | [ ] |
| `docker-compose.yml` | Services for `db` (postgres+pgvector image), `backend`, `frontend`, and `chainlit` (if used); named volumes for Postgres data; healthchecks; correct `depends_on` ordering | [ ] |
| `LICENSE` | Optional, but include if the starter repo had one | [ ] |
| `docs/` (optional) | Architecture diagram, ADRs (architectural decision records) if you split these out of the README | [ ] |

---

## 2. Backend — `/backend`

### 2.1 Application structure
| File/Dir | Contents | ✅ |
|---|---|---|
| `app/main.py` | FastAPI app instance, router registration, CORS middleware, startup/shutdown events (DB pool init/teardown) | [ ] |
| `app/core/config.py` | Pydantic `Settings` class reading from env (DB URL, LLM API key, embedding model name, chunk size/overlap, upload size limit) | [ ] |
| `app/db/session.py` | Async SQLAlchemy engine/session (or asyncpg pool) | [ ] |
| `app/db/models.py` | ORM models: `Document`, `Chunk` (with `vector` column), timestamps | [ ] |
| `app/schemas/` | Pydantic request/response models for upload, chat, health | [ ] |
| `app/api/routes/upload.py` | `POST /documents` (or similar) — accepts PDF, validates type/size, triggers ingestion | [ ] |
| `app/api/routes/chat.py` | `POST /chat` — accepts query, runs retrieval + generation, returns grounded answer + **structured citation list (chunk id, document, page number)** for Chicago-style superscript rendering on the frontend | [ ] |
| `app/api/routes/health.py` | `GET /health` — checks DB connectivity | [ ] |
| `app/services/ingestion.py` | PDF text extraction **with page number preserved per chunk**, chunking logic (size/overlap documented) | [ ] |
| `app/services/embeddings.py` | Embedding generation (model name explicit, batched calls) | [ ] |
| `app/services/retrieval.py` | Vector similarity search against pgvector (top-k, distance metric documented) | [ ] |
| `app/services/generation.py` | Prompt construction (system prompt grounding rules), LLM call, **citation attachment mapping each claim to its source chunk's page number** (assembled from retrieved metadata, not model-generated text) | [ ] |

### 2.2 Database migration/init
| File | Contents | ✅ |
|---|---|---|
| `db/init.sql` **or** `alembic/versions/*.py` | `CREATE EXTENSION IF NOT EXISTS vector;`, `documents` table, `chunks` table with `embedding vector(N)` column, **`page_number` column**, foreign key `chunks.document_id → documents.id` | [ ] |
| Index creation | `ivfflat` or `hnsw` index on the embedding column with distance metric noted (cosine vs L2) — and a note on why you picked it | [ ] |
| `alembic.ini` + `env.py` (if using Alembic) | Migration config pointed at env-based DB URL | [ ] |

### 2.3 Packaging & runtime
| File | Contents | ✅ |
|---|---|---|
| `pyproject.toml` | Dependencies via `uv`, Python version pin | [ ] |
| `uv.lock` | Committed for reproducible installs | [ ] |
| `Dockerfile` | Multi-stage build using `uv`, non-root user, `--break-system-packages` not needed inside container venv, small final image | [ ] |
| `.dockerignore` | Excludes `.venv`, `__pycache__`, tests cache, `.git` | [ ] |

### 2.4 Backend tests
| File | Contents | ✅ |
|---|---|---|
| `tests/conftest.py` | Test DB fixture (ideally a separate pgvector-enabled test DB or transactional rollback per test) | [ ] |
| `tests/test_upload.py` | Valid PDF accepted, non-PDF rejected, oversized file rejected, ingestion actually creates chunks | [ ] |
| `tests/test_chat.py` | Query returns an answer, answer is grounded (mock LLM/embeddings for determinism), empty-corpus edge case handled gracefully | [ ] |
| `tests/test_retrieval.py` | Similarity search returns expected ordering on known fixture vectors | [ ] |
| Test run command documented in README | e.g. `uv run pytest` | [ ] |

---

## 3. Frontend — `/frontend` (Next.js)

| File/Dir | Contents | ✅ |
|---|---|---|
| `app/page.tsx` or `pages/index.tsx` | Chat interface — message list, input box, loading/streaming state, error state, **inline superscript citations + Chicago-style reference list per message** | [ ] |
| `app/upload/page.tsx` | Dedicated PDF upload page — drag/drop or file picker, upload progress, success/error feedback, list of ingested docs, **fully responsive layout across mobile/tablet/desktop** | [ ] |
| `components/ChatWindow.tsx`, `MessageBubble.tsx` | Reusable chat UI pieces, **including a `Citation`/`FootnoteList` component rendering superscript markers + Chicago-style reference entries** | [ ] |
| `components/UploadForm.tsx` | Upload UI logic, calls backend `/documents` endpoint | [ ] |
| `lib/api.ts` | Typed API client wrapping backend base URL (env-driven, not hardcoded `localhost`) | [ ] |
| `.env.local.example` | `NEXT_PUBLIC_API_BASE_URL` and any other frontend-facing vars | [ ] |
| `package.json` | Scripts: `dev`, `build`, `start`, `test` | [ ] |
| `Dockerfile` | Production build (`next build` + `next start`), or standalone output mode | [ ] |
| `__tests__/` or `tests/` | Component tests (Jest + React Testing Library) for chat + upload flows; optional Playwright/Cypress e2e | [ ] |
| Test run command documented in README | e.g. `npm test` | [ ] |

---

## 4. Chainlit Chat UI — `/chainlit_app` (only if you kept/used it)

| File | Contents | ✅ |
|---|---|---|
| `app.py` | Chainlit entrypoint calling the same backend retrieval/generation services (avoid duplicating RAG logic — call the FastAPI backend or shared service module) | [ ] |
| `chainlit.md` | Welcome screen text | [ ] |
| `.chainlit/config.toml` | Chainlit config | [ ] |
| `Dockerfile` | If run as a separate container | [ ] |
| Note in README | Clarify whether Chainlit is primary, alternative, or removed — and why | [ ] |

---

## 5. CI/CD (optional but strengthens the "commit frequently" and "production-quality thinking" asks)

| File | Contents | ✅ |
|---|---|---|
| `.github/workflows/backend-tests.yml` | Spins up Postgres+pgvector service container, runs `uv run pytest` on push/PR | [ ] |
| `.github/workflows/frontend-tests.yml` | `npm ci && npm test` | [ ] |
| `.github/workflows/lint.yml` (optional) | Ruff/Black + ESLint | [ ] |

---

## 6. README.md — Required Content Checklist

This is the single most-graded file. Check every sub-item:

- [ ] **Overview**: what the app does, in 2–4 sentences
- [ ] **Architecture diagram or ASCII summary**: frontend ↔ backend ↔ Postgres/pgvector ↔ LLM provider
- [ ] **Tech stack table**: what you kept from starter vs substituted, and *why*
- [ ] **Local run instructions** (step-by-step, copy-pasteable):
  - [ ] Prerequisites (Docker, Docker Compose version, Node version, Python/`uv` version)
  - [ ] Clone/fork instructions
  - [ ] `.env` setup step (copy from `.env.example`)
  - [ ] Single command or ordered commands to bring the whole stack up (`docker compose up --build`)
  - [ ] How to confirm it's working (URLs to hit: `localhost:3000`, `localhost:8000`, `localhost:6100/docs`)
  - [ ] How to run migrations if not automatic on container start
- [ ] **Testing instructions**: exact commands for backend tests and frontend tests
- [ ] **Production deployment plan** (written outline, not code):
  - [ ] Cloud provider choice + reasoning
  - [ ] CI/CD strategy (build → test → deploy stages, what triggers deploy)
  - [ ] Infra considerations: managed Postgres w/ pgvector support, container hosting, secrets management, autoscaling, PDF storage (object storage vs local disk), observability/logging
- [ ] **Assumptions** section (see Section 9 below — paste your final list here)
- [ ] **Architectural decisions & trade-offs** (bonus item — explicit if you're claiming it)
- [ ] **Additional service layers** you added (caching, background job queue, rate limiting) and why (bonus item)

---

## 7. Assumptions to Explicitly State and Double-Check

Go through each — if you made a call, it needs a one-line justification in the README, not just in your head.

- [ ] **LLM provider & model**: which one, why, is the API key handled via env var only (never hardcoded)
- [ ] **Embedding model**: which one, dimensionality, and that it matches the `vector(N)` column size in your schema
- [ ] **Chunking strategy**: chunk size, overlap, splitter used, and why that choice suits PDF/health-domain content
- [ ] **Top-k retrieval value** and distance metric (cosine vs L2) — justified, not arbitrary
- [ ] **Auth**: assessment doesn't mention auth — confirm you've stated whether you added any (and why) or explicitly left it out as out-of-scope
- [ ] **File upload limits**: max size, PDF-only validation, what happens on corrupt/scanned (non-text) PDFs
- [ ] **Multi-document handling**: can a query span multiple uploaded PDFs, or is retrieval scoped per-document
- [ ] **Chat history persistence**: stored in DB, session-only, or none — stated explicitly
- [ ] **Grounding/hallucination guardrail**: what stops the model from answering outside the retrieved context (system prompt rule, refusal behavior when no relevant chunks found)
- [ ] **Source citation in responses**: does the chat UI show which document/chunk backed the answer
- [ ] **Citation format**: confirm you're using Chicago **notes-bibliography style** (superscript + numbered footnote list) rather than author-date style — state this explicitly since "Chicago-style" has two variants and a reviewer shouldn't have to guess which
- [ ] **Responsive breakpoints chosen**: state the specific widths you designed/tested against (e.g., 375 / 768 / 1024 / 1440px) so the reviewer knows your testing scope
- [ ] **Environment**: any WSL2/Docker-specific setup notes carried over from your dev environment that a reviewer on native Linux/Mac should know about (e.g., the Docker build performance fix you applied via `uv`)
- [ ] **Scalability statement**: what "scalable" means in your submission — async I/O, connection pooling, background ingestion tasks — stated even if not fully implemented, as a documented next step
- [ ] **Security statement**: input validation, CORS policy, no secrets in repo, SQL injection prevention via ORM/parameterized queries — stated explicitly

---

## 8. Submission Mechanics (easy to miss, hard to fix after deadline)

- [ ] Repository is an actual **fork** of the provided starter repo (not a fresh repo with copied files) — confirm fork lineage is visible on GitHub
- [ ] Commit history shows **incremental, descriptive commits** across the work session — not one giant final commit
- [ ] Repo visibility is set correctly for how you were asked to share it (private + reviewer invited, or public) — re-check the original instructions/email for which was requested
- [ ] `.env` (real secrets) is **not** committed; `.env.example` **is**
- [ ] All three services (frontend, backend, chat UI if separate) actually build and start via the documented steps — test this from a **clean clone**, not your working directory
- [ ] Submitted link goes to the correct branch (usually `main`) with everything merged in
- [ ] Submission made before the 72-hour deadline, with no post-deadline commits planned

---

## 9. Final Verification — Clean-Clone Dry Run

Before you submit, actually do this:

- [ ] `git clone` your fork into a brand-new empty directory (not your dev folder)
- [ ] Follow your own README instructions verbatim, no shortcuts from memory
- [ ] Confirm `docker compose up --build` succeeds with no manual intervention beyond what's documented
- [ ] Upload a real PDF through the UI and confirm it ingests (check DB row count / chunk count)
- [ ] Ask a question grounded in that PDF and confirm the answer carries correctly numbered superscript citations, and that each footnote's page number matches the actual page in the source PDF — check at least 2–3 by hand
- [ ] Ask a question **not** covered by any uploaded document and confirm the system doesn't hallucinate a confident answer
- [ ] Resize the browser (or use dev-tools device toolbar) from 375px through 1440px+ on the upload page and confirm no broken layout, clipped controls, or horizontal scroll at any width
- [ ] Run backend tests: all pass
- [ ] Run frontend tests: all pass
- [ ] Re-read the README once more as if you were the reviewer seeing this for the first time

---

## 10. Repo Integrity & Access Control — Instructions for the Coding Agent

> **To the agent:** run this section last, in order, immediately before submission. Replace `<repo_path>`, `<fork_url>`, and `<owner>/<repo>` with actual values. Treat every "Expected" line as a hard gate — if actual output doesn't match, stop, fix the root cause, and re-run that step before moving to the next one. Do not skip a step because a later one "should" catch the same issue.

### Step 1 — Confirm nothing local is unsynced
```bash
git -C <repo_path> status --porcelain
```
Expected: no output. If output appears, commit or stash it, then re-run.

```bash
git -C <repo_path> fetch origin
git -C <repo_path> log origin/main..HEAD --oneline
```
Expected: no output (nothing ahead of `origin/main`). If output appears, push and re-check:
```bash
git -C <repo_path> push origin main
git -C <repo_path> push origin --all
git -C <repo_path> push origin --tags
```

### Step 2 — Prove the fork matches the local build byte-for-byte
```bash
rm -rf /tmp/verify-clone
git clone <fork_url> /tmp/verify-clone
diff -rq \
  --exclude=.git --exclude=node_modules --exclude=.venv \
  --exclude=__pycache__ --exclude=.next --exclude=uv.lock \
  <repo_path> /tmp/verify-clone
```
Expected: no output. Any diff line means the fork is missing local work — return to Step 1, do not proceed.

### Step 3 — Validate the images build for multiple architectures
```bash
docker buildx build --platform linux/amd64,linux/arm64 -t backend-test ./backend
docker buildx build --platform linux/amd64,linux/arm64 -t frontend-test ./frontend
docker manifest inspect <postgres-pgvector-image> | grep -A2 architecture
```
Expected: both `buildx` commands exit 0 for **both** platforms, and the Postgres image manifest lists `arm64` alongside `amd64`. An `arm64`-only failure means a dependency lacks an arm64 wheel/binary — identify and pin an alternative, or document the limitation explicitly in the README if it can't be resolved.

### Step 4 — Normalize line endings and executable bits
```bash
cat > <repo_path>/.gitattributes << 'EOF'
* text=auto eol=lf
*.sh text eol=lf
EOF
git -C <repo_path> add --renormalize .
find <repo_path>/scripts -name "*.sh" -exec chmod +x {} \; 2>/dev/null
git -C <repo_path> add -A
git -C <repo_path> commit -m "chore: normalize line endings and script permissions for cross-platform execution"
git -C <repo_path> push origin main
```
Expected: commit succeeds (or is a no-op if already normalized) and pushes cleanly.

### Step 5 — Scan for host-absolute or WSL-specific paths
```bash
grep -rn "/mnt/c" <repo_path> --include="*.yml" --include="*.yaml" --include="Dockerfile*" --include="*.env*" --include="*.sh"
grep -rn "C:\\\\" <repo_path> --include="*.yml" --include="*.yaml"
```
Expected: no matches. Any match must be replaced with a relative or containerized path before proceeding — do not submit with a hardcoded host path.

### Step 6 — Full clean-environment run test
```bash
cd /tmp/verify-clone
cp .env.example .env
docker compose up --build -d
sleep 15
docker compose ps
curl -sf http://localhost:6100/health || echo "BACKEND HEALTH CHECK FAILED"
curl -sf http://localhost:3000 || echo "FRONTEND NOT RESPONDING"
docker compose down -v
```
Expected: all services show as running/healthy in `docker compose ps`, and both `curl` checks succeed with no `FAILED`/`NOT RESPONDING` output. Any failure here is a blocking issue — fix the underlying cause, don't patch around symptoms.

### Step 7 — Confirm default branch and tag the exact submission commit
```bash
gh repo view <owner>/<repo> --json defaultBranchRef
```
Expected: `defaultBranchRef.name` is the branch holding the final code (typically `main`). If it points to a stale or feature branch, either update the default branch in GitHub settings or merge final work into it first.

```bash
git -C <repo_path> tag lmh-submission
git -C <repo_path> push origin lmh-submission
```
This pins an unambiguous reference (`<fork_url>/tree/lmh-submission`) regardless of any later activity on `main`.

### Step 8 — Lock down write access
```bash
gh api repos/<owner>/<repo>/collaborators
```
Expected: only the owner listed. If any unintended collaborator appears:
```bash
gh api -X DELETE repos/<owner>/<repo>/collaborators/<username>
```

Apply branch protection to block direct pushes, including the owner's own:
```bash
gh api -X PUT repos/<owner>/<repo>/branches/main/protection \
  -F required_pull_request_reviews.required_approving_review_count=1 \
  -F enforce_admins=true \
  -F restrictions=null \
  -F required_status_checks=null
```
Expected: the API call returns 200. Confirm in GitHub UI under Settings → Branches that "Require a pull request before merging" and "Do not allow bypassing the above settings" are both checked for `main`.

### Step 9 — Archive the repo (only once submission receipt is confirmed)
```bash
gh api -X PATCH repos/<owner>/<repo> -F archived=true
```
⚠️ Do **not** run this until the assessment panel has confirmed the link is accessible and reviewable — archiving makes the entire repository read-only for everyone, including the owner, until manually unarchived. This is the strongest guarantee against any post-deadline change (accidental or otherwise), satisfying the instruction not to modify the repo after submission.

### Step 10 — Report back
Output a final pass/fail summary for Steps 1–9, the confirmed default branch, the tagged submission reference (`<fork_url>/tree/lmh-submission`), and repo visibility/archive status — this is what gets handed to the human for the actual submission message.
