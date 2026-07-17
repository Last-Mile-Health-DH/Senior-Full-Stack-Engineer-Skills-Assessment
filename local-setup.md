# Local Setup

## Prerequisites
- Docker Engine 24+ (tested on 29.3.1)
- Docker Compose v2+ (tested on v5.1.0)
- On Windows, use Docker Desktop with WSL2 integration, and keep the repo inside the WSL2 filesystem for reasonable build performance.

## Setup
```bash
git clone <your-fork-url>
cd Senior-Engineer-AI-Digital-Health-Skills-Assessment
docker compose -p assessment up -d --build
```
Build completes in well under a minute with a warm cache, and a few minutes on a clean build. See the known issue below if the `chainlit_app` step appears to hang.

## Services

| Service | URL | Description |
| --- | --- | --- |
| Frontend / Instructions | http://localhost:3000 | Serves the assessment instructions |
| Chainlit Chat UI | http://localhost:8000 | Chat interface |
| Backend API | http://localhost:6100 | FastAPI backend |
| PostgreSQL | localhost:5432 | Database (pgvector) |

## Verifying the Setup
```bash
docker compose -p assessment ps
```
All four containers should show `Up`. No healthchecks are defined in the compose file, so `Up` is expected — `healthy` will not appear.

```bash
curl -o /dev/null -sw "%{http_code}\n" http://localhost:3000
curl -o /dev/null -sw "%{http_code}\n" http://localhost:8000
curl -o /dev/null -sw "%{http_code}\n" http://localhost:6100
docker compose -p assessment exec -T relational_db pg_isready -U postgres
```
Each HTTP check should return `200`. Postgres should report `accepting connections`.

## Known Issue: Slow chainlit_app Dependency Install

`chainlit_app`'s dependency tree (`chainlit` → `literalai` → `traceloop-sdk` → the `opentelemetry-instrumentation-*` family) causes pip's resolver to backtrack extensively, which can stretch a plain `pip install` to 60–90+ minutes. This is a resolver characteristic, not a network or hardware issue — `docker stats` will show sustained single-core CPU use rather than a stall.

The fix, already applied in `chainlit_app/Dockerfile`, is to install with `uv` instead of pip:
```dockerfile
RUN pip install --no-cache-dir uv
RUN uv pip install --system --no-cache -r requirements.txt
```
This resolves the same dependency graph in under a minute.

## Troubleshooting

**Port already in use** — identify and stop the conflicting process, or remap the port in `docker-compose.yaml`:
```bash
ss -ltnp | grep -E ':3000|:8000|:6100|:5432'
```

**Build fails or seems stuck** — rebuild the affected service directly with verbose output:
```bash
docker build --no-cache --progress=plain -t debug ./chainlit_app
```
Swap in `./backend` or `./frontend` as needed. If it's the `chainlit_app` pip step, see the known issue above before assuming it's frozen.

**Container exits immediately**:
```bash
docker compose -p assessment logs <service>
```
Service names: `frontend`, `chainlit`, `backend`, `relational_db`.

## Shutdown
```bash
docker compose -p assessment down
```