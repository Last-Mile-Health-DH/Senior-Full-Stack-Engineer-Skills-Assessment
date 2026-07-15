# Local Setup

## Prerequisites

- Docker Engine 24+ (last verified locally on Docker 29.3.1)
- Docker Compose v2+
- Node 20+ only for running frontend commands outside Docker
- Python 3.12 only for running backend or gold-standard commands outside Docker

On Windows, use Docker Desktop with WSL2 integration and keep the repository inside the WSL2 filesystem for better build performance.

## Setup

```sh
git clone <your-fork-url>
cd Senior-Engineer-AI-Digital-Health-Skills-Assessment
cp .env.example .env
docker compose -p assessment up -d --build
```

If the database volume is new or has been reset, run migrations:

```sh
docker compose -p assessment exec backend alembic upgrade head
```

## Services

| Service | URL | Description |
|---|---|---|
| **Next.js chat** | http://localhost:3000 | Chat surface with sidebar navigation and a `+` upload button |
| **Chainlit chat** | http://localhost:8000 | Equivalent chat surface with a `+ Upload PDF` header button |
| Upload page | http://localhost:3000/documents | The single place PDFs are added, for either chat surface |
| Backend API | http://localhost:6100 | FastAPI backend |
| Backend health | http://localhost:6100/health | App and database health |
| Backend docs | http://localhost:6100/docs | OpenAPI documentation |
| PostgreSQL | localhost:5432 | PostgreSQL 16 with pgvector |

## Environment Requirements and Known Portability Risks

Everything below was measured on the development machine (x86_64 / WSL2 / Docker 24). It is stated plainly because a warm local Docker cache hides exactly the failures a reviewer hits first.

### What you need

| Resource | Requirement | Why |
|---|---|---|
| Disk | **~10 GB free** | Images total ~5.7 GB: backend **2.92 GB** (torch + sentence-transformers + baked reranker weights), frontend 1.43 GB, Chainlit 708 MB, pgvector 621 MB. Build layers need headroom on top. |
| RAM | **4 GB free** (8 GB comfortable) | Idle runtime is modest — backend 180 MB, Chainlit 87 MB, frontend 58 MB, Postgres 120 MB. The cost is at *build* time, not run time. |
| CPU | Any x86_64 or arm64 | No GPU is needed or used. The cross-encoder runs on CPU. |
| Ports | **3000, 5432, 6100, 8000** free | See the port-conflict row below — 5432 is the usual culprit. |
| Docker | Engine 24+, Compose v2 | Compose v2 syntax and healthcheck behavior. |
| First cold build | **~20 minutes**, needs network | Measured: `docker compose build --no-cache backend` took **20m 01s** on the dev machine. Dominated by the torch/sentence-transformers install and the reranker-weight prefetch. Subsequent builds are cached and take seconds. |

### Known risks, and what was done about each

| Risk | Impact if unhandled | Status |
|---|---|---|
| **CPU architecture (Apple Silicon / arm64)** | `torch==2.9.1+cpu` is published **only for x86_64**. Pinned unconditionally, `pip install` fails and the backend image cannot be built at all on an M-series Mac. | **Fixed.** `backend/requirements.txt` now pins per-architecture with PEP 508 markers (`+cpu` on x86_64, the plain — already CPU-only — wheel on aarch64). The `pgvector/pgvector:pg16` image publishes arm64. **Not yet executed on an arm64 host**, so this is a reasoned fix, not a verified one. |
| **Reranker weights downloaded at runtime** | The cross-encoder (~90 MB) was fetched from Hugging Face on the **first chat request**, so the reviewer's first question was slow, and failed outright with no network. Each gunicorn worker would fetch its own copy. | **Fixed.** Weights are baked into the image at build time (`HF_HOME=/opt/hf`) and `HF_HUB_OFFLINE=1` forbids any runtime fetch. CI asserts the reranker loads offline. |
| **Schema not migrated on a fresh volume** | The backend started "successfully" and then 500'd on every request, because no tables existed until someone ran Alembic by hand. | **Fixed.** `backend/startup_unix.sh` runs `alembic upgrade head` before gunicorn. `docker compose up` is now sufficient on its own. (In production this belongs in a separate migration task — see `DEPLOYMENT.md`.) |
| **Running the test suite wipes your data** | The pytest fixtures `alembic downgrade base` against the **same database the running stack uses**. Running the suite deletes every document you uploaded. | **Documented, by design.** Deterministic tests own the database. Do not run `pytest` against a stack whose uploaded documents you want to keep; re-run `alembic upgrade head` afterwards (the container entrypoint does this on restart). |
| **Port 5432 already in use** | `docker compose up` fails, or worse, the backend silently talks to *your* local Postgres, which has no pgvector. | Stop the local Postgres, or remap the port in `docker-compose.yaml`. The backend connects over the compose network, so remapping the host port is safe. |
| **Stale database volume from an earlier run** | Migrations conflict, or old documents appear. | `docker compose -p assessment down -v` to drop the volume, then `up -d --build`. |
| **Missing `.env`** | Compose substitutes empty values; most defaults still work, but nothing is explicit. | `cp .env.example .env` before the first `up`. No real secrets are needed for the local stack. |
| **Docker Desktop memory cap** | The default 2 GB cap on some Docker Desktop installs will OOM the backend build during the torch install. | Raise the VM memory limit to at least 4 GB (Docker Desktop → Settings → Resources). |
| **Gunicorn worker count vs. memory** | 4 workers each hold a torch runtime. On a small machine this is the memory hotspot. | `--preload` loads the app once before forking. Set `WEB_CONCURRENCY=2` to halve it on a constrained machine. |
| **Playwright system libraries** | `playwright install` fetches the browser but not its system libs; Chromium then fails with `libnspr4.so: cannot open shared object file`. Installing them needs `sudo`. | Use `npx playwright install --with-deps chromium`. Playwright is only needed for e2e; nothing else depends on it. |
| **Node version** | The frontend is built and tested on Node 20. Older majors will fail on Next 16. | Use Node 20+. CI pins 20. |
| **First request after boot is slower** | Even with baked weights, the cross-encoder is loaded lazily into memory on first use (a few seconds). | Expected. Subsequent requests are warm, and repeat questions are served from the cache. |

**How this is verified rather than asserted:** `.github/workflows/ci.yml` builds every image with `docker compose build --no-cache` from a clean checkout on a GitHub-hosted runner — a machine that is not the author's, with no warm cache — then brings the whole stack up, waits for health (which also proves migrations applied to an empty volume), asserts the reranker loads with `HF_HUB_OFFLINE=1`, runs the full backend suite, the integration suite, an Alembic down/up round trip, and Playwright against both chat surfaces. That is the check that a reviewer's cold clone will work; a green local run is not.

## Which chat surface should a reviewer use?

**Either. They are equivalent.** The starter allows Chainlit "in place of or alongside the Next.js frontend", and this build keeps both. Both surfaces `POST /api/v1/chat` and render the same answer and the same `Sources` list — no retrieval, generation, or citation logic lives in either client, so they cannot disagree. If they ever do, that is a bug.

Suggested reviewer path:

1. Open http://localhost:3000 and press **`+`** in the composer (or **`+ Upload PDF`** in Chainlit's header). Both land on the upload page.
2. Upload a PDF and wait for its status to read **Ready**. Until then, chat will politely say the document is still being prepared rather than pretending it has nothing.
3. Ask a question about the document on **either** surface. The answer carries a superscript at the end of each sentence it supports, and a `Sources` list underneath naming the document and page.
4. Ask something the document does not cover. You should get "I could not find that in your documents" with **no** sources — not a plausible guess.

## Verifying the Setup

```sh
docker compose -p assessment ps
curl -s http://localhost:6100/health
curl -I http://localhost:6100/docs
curl -I http://localhost:3000
curl -I http://localhost:3000/documents
curl -I http://localhost:8000
docker compose -p assessment exec -T relational_db pg_isready -U postgres
```

Expected backend health response:

```json
{"status":"ok","database":"ok"}
```

Document-management API calls are public in the local reviewer stack:

```sh
curl -s http://localhost:6100/api/v1/documents
```

No IAM provider, hosted auth provider, browser token, or bearer header is required for upload/list/status/delete document routes. `/api/v1/auth/session` remains available only if you disable anonymous chat with `ANONYMOUS_CHAT_ALLOWED=false`.

Run the browser smoke after the stack is healthy:

```sh
npm install --prefix frontend
npm --prefix frontend run playwright:install
PLAYWRIGHT_BASE_URL=http://localhost:3000 npm --prefix frontend run test:e2e
```

## Known Build Notes

The backend image installs `poppler-utils` and `tesseract-ocr` at the system layer for PDF rasterization and OCR. The Docker build also pins CPU-only torch before `sentence-transformers` to avoid CUDA wheel downloads.

The Chainlit dependency tree is installed with `uv pip install` in `chainlit_app/Dockerfile`. This avoids long pip resolver backtracking through the Chainlit/OpenTelemetry packages.

## Troubleshooting

**Port already in use**

```sh
ss -ltnp | grep -E ':3000|:8000|:6100|:5432'
```

Stop the conflicting process or remap the port in `docker-compose.yaml`.

**Backend database errors**

```sh
docker compose -p assessment exec backend alembic upgrade head
docker compose -p assessment logs backend
```

**Build fails or seems stuck**

```sh
docker compose -p assessment build backend
docker compose -p assessment build chainlit
docker compose -p assessment build frontend
```

**Container exits immediately**

```sh
docker compose -p assessment logs <service>
```

Service names are `frontend`, `chainlit`, `backend`, and `relational_db`.

## Shutdown

```sh
docker compose -p assessment down
```
