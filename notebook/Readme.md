### Workflow
Building a basic RAG pipeline, this can be enhanced by building agents. The advantage of agents is ability to further query the data and have additional queries automatically generated through the *agentic loop*

### Technologies
- Postgres/Pgvector to store document vectors
- Semantic transformation to vectors - have used *SentenceTransformer* for this exercise
  > For Production, *Onnxruntime* transformer can be used because it is much lighter



### Challenges

The docker install threw me off since it was taking a non-trivial amount of time to install. 

Manually located the instructions file from 
<code>backend > app > home > routes.py</code>

locally (macos setup)
![local docker](locally.png)

On github codespace
![using github codespaces](codespaces.png)

---

## Running the app

Three independent services, each with its own dependency management, live under `app/`:

| Service | Tech | Port | Directory |
|---|---|---|---|
| Backend | FastAPI (Python, `uv`) | `6100` | `app/backend` |
| Frontend | React + Vite + react-router (TypeScript) | `3000` | `app/frontend` |
| Chat UI | Chainlit (Python, `uv`) | `8000` | `app/chainlit` |
| Database | PostgreSQL + pgvector | `5432` | — |

Copy the root env file and fill in your keys before starting anything:

```
cp .env.example .env
# then edit .env: set OPENAI_API_KEY and DATABASE_URL
```

Postgres must already be running with the `pgvector` extension **available** (e.g. the
`pgvector/pgvector` Docker image, or `brew install pgvector` against a local Postgres) — the backend
runs `CREATE EXTENSION IF NOT EXISTS vector` and creates its own tables/indexes on startup, but it can't
install the extension binary itself.

### Backend (FastAPI)

```
cd app/backend
uv sync
uv run uvicorn backend.main:app --port 6100 --reload
```

On startup it idempotently creates the `documents` table and an HNSW index if they don't already exist —
no manual schema setup needed once Postgres+pgvector is reachable.

**Tests** (fast, no live Postgres or OpenAI key required — DB/embedder/LLM are mocked):
```
uv run pytest
```
**Integration test** (hits a real local Postgres+pgvector and calls OpenAI for real, end-to-end upload → chat):
```
RUN_INTEGRATION_TESTS=1 uv run pytest -m integration
```

Endpoints: `GET /health`, `POST /documents` (multipart PDF upload), `POST /chat` (`{"question": "..."}`).

### Frontend (React)

```
cd app/frontend
npm install
cp .env.example .env
npm run dev
```
Serves at `http://localhost:3000` — **the dev port is pinned in `vite.config.ts`** (Vite's default is
5173) because the backend's CORS allow-list only permits `localhost:3000`; running on a different port
will cause every API call to fail with a CORS error.

**Tests**:
```
npm test
```

### Chat UI (Chainlit)

An alternative chat interface to the React frontend's Chat page — a thin client that calls the same
backend `/chat` endpoint. Requires the backend to be running.

```
cd app/chainlit
uv sync
uv run chainlit run app.py --port 8000 -w
```

**Tests** (mocked HTTP calls, no live backend required):
```
uv run pytest
```

---

## Architectural decisions & trade-offs

- **`rag_builder.py` is vendored, not imported.** The backend copies `RAGPgVector` into
  `app/backend/src/backend/rag/rag_builder.py` rather than reaching across to the repo-root copy via
  `sys.path`, so the backend stays an independently deployable unit with its own dependency graph. The
  trade-off is two copies of the same ~90 lines that can drift; acceptable for this scope, worth
  revisiting (e.g. an installable shared package) if the notebook and backend need to stay in lockstep
  long-term.
- **Chainlit calls the backend's REST API rather than duplicating RAG logic.** This keeps a single
  source of truth for retrieval/generation — Chainlit is purely a UI, and inherits backend behavior
  changes automatically instead of needing a third vendored copy of `rag_builder.py`.
- **Schema DDL auto-runs (idempotently) on backend startup**, not via a migration tool. Given the raw
  `psycopg` + hand-written SQL decision (no ORM), full migration tooling (Alembic, etc.) was judged out
  of scope; this means there's no versioned migration history, which a longer-lived production service
  would want.
- **Uploaded PDFs are processed in-memory only** — never written to disk. Smaller security/audit
  surface, but there's no way to re-inspect the original file after ingestion; a production version might
  persist originals to object storage (S3) alongside the extracted chunks.
- **`GET /health` always returns 200** with a `database`/`embedder_loaded` status field, rather than a
  503 on DB failure. Simpler for local dev; a real deployment behind a load balancer doing health-based
  routing would likely want a proper 503 to double as a readiness probe.
- **Chakra UI + Tailwind CSS together** (frontend styling). This is an unusual pairing — Chakra ships its
  own styling engine and both systems want to own global resets. Mitigated by importing only Tailwind's
  theme + utility layers (not `preflight.css`, which is what would fight Chakra's base styles) and a
  strict split: Chakra owns interactive/structured components (buttons, inputs, alerts, badges), Tailwind
  is reserved for one-off utility tweaks on plain wrapper elements (e.g. scroll containers) — never
  applied as a class override on a Chakra component itself. A from-scratch decision would likely pick one
  system; this split-responsibility rule is what makes the combination workable.
- **`react-router` in declarative mode** (`BrowserRouter`/`Routes`/`Route`), not framework mode. This is
  a 2-route SPA on a plain Vite toolchain — framework mode's file-based routing and data
  loaders/actions would be more machinery than the app needs.
- **Chat history is client-side only**, lifted into `AppLayout` (not `ChatPage`) so it survives
  navigating to `/upload` and back, but it's lost on a hard refresh — there's no backend session/history
  storage in this scope.
- **PDF client-side validation is type/extension-only** (hard block); file size only produces a
  non-blocking warning, since the backend is authoritative on the real upload limit and the frontend
  shouldn't hardcode a cap that could drift from it.

## Production deployment plan

**Cloud provider**: AWS. Backend and Chainlit as containerized services on **ECS Fargate** (stateless,
autoscale on CPU/request count) behind an **ALB**; frontend as a static build on **S3 + CloudFront**;
database on **RDS for PostgreSQL** with the `pgvector` extension enabled (RDS supports it on recent
Postgres versions), in a private subnet reachable only from the Fargate tasks.

**CI/CD** (GitHub Actions):
- On every PR: lint + typecheck + test each service independently (`uv run pytest` for backend/chainlit,
  `npm test` + `tsc -b` for frontend) as a matrix job; fail fast, no deploy.
- On merge to `main`: build Docker images per service, push to **ECR**, then update the corresponding
  ECS service (`aws ecs update-service --force-new-deployment` or a proper CD tool like CodeDeploy for
  blue/green); frontend build artifacts sync to S3 with a CloudFront invalidation.
- Schema init already runs idempotently on backend startup, so no separate migration step is required for
  this scope — a longer-lived service would run Alembic migrations as an explicit pre-deploy step instead.

**Infrastructure considerations**:
- Secrets (`OPENAI_API_KEY`, `DATABASE_URL`, etc.) via **AWS Secrets Manager**, injected as task
  environment variables — never committed, never baked into images.
- `CORS_ORIGINS` set per-environment to the actual deployed frontend domain, not `localhost`.
- `/health` semantics should move to "503 on DB-down" in production so the ALB target group can actually
  route around an unhealthy instance (see trade-offs above).
- The `SentenceTransformer` embedder loads into memory once per instance at startup — size Fargate task
  memory accordingly and consider a minimum warm instance count to avoid cold-start latency on scale-out.
- Connection pool size × number of backend replicas must stay under RDS's `max_connections`; add
  **PgBouncer** (or RDS Proxy) if the service scales beyond a handful of replicas.
- Structured logging + an error tracker (e.g. Sentry) wired into the existing global exception handler for
  production visibility beyond the current server-side traceback logging.