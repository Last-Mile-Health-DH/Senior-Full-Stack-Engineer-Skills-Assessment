# Production Deployment Plan

This document is the production deployment plan for the Last Mile Health RAG platform. It is a plan, not evidence of a deployment: there is no Terraform/CDK/CloudFormation stack and nothing is deployed. What *does* exist is CI — `.github/workflows/ci.yml` builds every image with `--no-cache` from a clean checkout, brings the full stack up, and runs every suite, so the build-and-test half of the pipeline below is real and running. The deploy half is design.

Contents: [cloud provider choice](#cloud-provider-choice) · [target architecture](#target-aws-architecture) · [compute](#lambda-compute-rationale) · [models and cost](#bedrock-model-switching-and-cost-optimization) · [environments](#environments-and-configuration) · [CI/CD](#cicd-strategy) · [reliability](#reliability-and-scalability) · [observability](#observability-and-slos) · [security](#security) · [disaster recovery](#disaster-recovery) · [data and migrations](#migration-and-data-strategy) · [open items](#known-gaps-and-open-items)

## Cloud Provider Choice

**Choice: AWS.** The decision is driven by one hard requirement and one soft one.

The hard requirement is **managed PostgreSQL with `pgvector`**. Retrieval, the caches, audit logs, and evaluation all live in one PostgreSQL database, and the vector index is a pgvector HNSW index in that same database. A provider that cannot run pgvector on its managed PostgreSQL would force either a self-managed database or a separate vector store — the second option splits the transactional boundary that currently makes "retrieve, filter, cache, audit" a single consistent unit, which is a real architectural loss, not a procurement detail.

The soft requirement is a **managed model layer with per-model cost attribution**, because `MODEL_PRICING_JSON`, the nightly `JudgeAgent` grading, and the anomaly/cost alerts all assume model spend is attributable per call.

| Provider | Fit | Why not chosen |
|---|---|---|
| **AWS** (chosen) | RDS PostgreSQL supports `pgvector`; Fargate runs the current containers unchanged; Bedrock centralizes model access, permissions, and billing; S3/KMS/Secrets Manager/CloudWatch cover the rest | — |
| GCP | Cloud SQL supports `pgvector`; Cloud Run is a good fit for these containers; Vertex AI is a credible Bedrock equivalent | A genuinely viable alternative. Not chosen on technical grounds — AWS is assumed as the incumbent. If the organization is GCP-first, this plan ports almost one-for-one: Cloud Run for Fargate, Cloud SQL for RDS, GCS for S3, Secret Manager for Secrets Manager, Vertex for Bedrock. |
| Azure | Azure Database for PostgreSQL supports `pgvector`; Container Apps and Azure OpenAI are the equivalents | Same as GCP: viable, not chosen. Would be the right answer in a Microsoft-first organization. |
| Fly.io / Render / Railway | Would run the compose stack with very little work | No managed pgvector story that meets the backup/Multi-AZ/PITR bar below, and no model-governance layer. Fine for a demo, not for clinical guidance data. |
| Self-managed Kubernetes | Maximum control | Operational overhead is not justified by this system's scale, and buys nothing the managed services do not already give. |

**What would change this decision:** if the model provider had to be Anthropic's API directly (rather than through Bedrock), the provider choice would weaken to "wherever the database and containers are cheapest to operate", because the model layer would no longer be an AWS-native concern. The architecture keeps the generation client behind a `GenerationClient` protocol precisely so that swap is a configuration change, not a rewrite.

## Target AWS Architecture

```text
CloudFront + WAF
      |
      v
Application Load Balancer or API Gateway
      |
      +--> Next.js frontend
      +--> Chainlit chat UI, wired to FastAPI /api/v1/chat
      +--> FastAPI backend
              |
              +--> RDS PostgreSQL 16 + pgvector, private subnets
              +--> S3 private buckets for PDFs and page images
              +--> Bedrock or hosted model providers
              +--> Secrets Manager / SSM Parameter Store
              +--> CloudWatch logs, metrics, traces, dashboards
```

Recommended components:

| Layer | AWS choice | Rationale |
|---|---|---|
| Frontend | S3 + CloudFront for a static build, or ECS Fargate/App Runner for current Next.js server runtime | CloudFront gives edge caching when static; Fargate/App Runner avoids changing runtime assumptions. |
| Backend API | ECS Fargate for the current container | Warm container is better for local reranker loading, PDF parsing/OCR, and async DB pooling. |
| Chainlit | ECS Fargate behind ALB, pointed at the private FastAPI service URL | Keeps chat isolated while sharing backend logic through `/api/v1/chat`. |
| Database | Amazon RDS PostgreSQL 16 with pgvector | Managed backups, Multi-AZ, encryption, and PostgreSQL extension support. |
| Object storage | Amazon S3 private buckets | Durable storage for uploaded PDFs and rasterized page images. |
| Secrets | Secrets Manager or SSM Parameter Store | Runtime injection without committing or baking secrets into images. |
| Network boundary | CloudFront/WAF + ALB or API Gateway | Rate, bot, and request filtering before app services. |
| Networking | VPC with public ALB/API boundary and private app/database subnets | Database is never public; app egress is controlled. |
| IAM | Task/Lambda roles with least privilege | S3, Bedrock, CloudWatch, and secret access are scoped per workload. |

## Lambda Compute Rationale

Lambda is a strong fit for bursty, event-driven and idle-cost-sensitive workloads:

- corpus evaluation triggers
- scheduled grading kicks
- lightweight ingestion dispatch
- post-upload fanout events
- small health/smoke handlers
- notification and anomaly alert delivery

Lambda is not ideal for long-running local model inference, local CrossEncoder reranking, heavyweight CPU/GPU workloads, large PDF OCR/rasterization, or request paths that need a warm database pool without RDS Proxy. Those workloads should use ECS Fargate, Bedrock-hosted models, or queue-backed workers.

If the API is split onto Lambda, use API Gateway + Lambda + RDS Proxy. Mitigate cold starts with small deployment packages, provisioned concurrency for latency-sensitive handlers, model calls delegated to Bedrock, and no local ML model loading in function startup.

| Compute option | Use when | Trade-off |
|---|---|---|
| Lambda | Bursty jobs, event triggers, lightweight handlers | Cold starts, timeout limits, RDS Proxy needed for pooling |
| ECS Fargate | Current backend, OCR/PDF work, local reranker, persistent pool | Higher idle cost than Lambda |
| App Runner | Simple container deploy with fewer knobs | Less VPC/routing control than ECS |
| EKS | Many services and platform team ownership | Too much operational overhead for this scope |
| EC2 | Full host control or special hardware | Manual patching/scaling burden |

## Bedrock Model Switching and Cost Optimization

Amazon Bedrock is the preferred production model access layer where organizational governance, centralized model permissions, and AWS-native billing controls are required.

Routing policy:

- fast/low-cost model: summaries, classification, grading prechecks, query expansion, and low-risk transformations
- stronger model: final grounded answer generation and complex clinical reasoning
- pinned judge model: `JudgeAgent` uses a fixed model, temperature, and rubric version so trends are reproducible

Cost controls:

- Track per-model input/output token usage and cost through `MODEL_PRICING_JSON` or a Bedrock-aware equivalent.
- Configure AWS Budgets and CloudWatch anomaly alerts for model cost spikes.
- Keep exact cache, semantic cache, and prompt caching enabled only where safe.
- Run refusal/grounding gates before caching generated answers.
- Preserve exact numeric grounding regardless of which model produces the answer.

## Reliability and Scalability

- FastAPI uses async request handling and async SQLAlchemy sessions.
- Use RDS Proxy when Lambda handlers connect to RDS.
- Keep scheduler jobs behind PostgreSQL advisory-lock singleton guards so horizontal replicas do not duplicate work.
- Make ingestion and gold-eval jobs idempotent around document content hashes, run IDs, and audit lineage.
- Move large PDF processing to queue/event-backed workers at scale: S3 upload event -> SQS/EventBridge -> worker/Lambda/ECS task.
- Set autoscaling boundaries separately for frontend, backend, Chainlit, and worker tasks.
- Run RDS Multi-AZ with automated backups and periodic restore tests.
- Use S3 versioning/lifecycle rules and KMS encryption for PDFs and page images.
- Add ALB/API readiness checks against `/health`, plus deeper smoke checks after deployment.
- Keep WAF and application rate limits active; tune per-IP/session limits from observed traffic.
- Build CloudWatch dashboards for p95 latency, 5xx rate, cache hit rate, grounding failures, cost, anomaly flags, and gold-eval score trends.

## Security

- No hardcoded secrets. `.env` stays local and ignored; production secrets are injected from Secrets Manager or SSM.
- JWT session tokens protect document-management endpoints; `ANONYMOUS_CHAT_ALLOWED` controls chat access.
- CORS must be explicit per environment.
- Upload validation checks PDF magic bytes, MIME allow-list, size, and page count.
- S3 buckets remain private with bucket policies, KMS encryption, and no public ACLs.
- RDS, S3, Secrets Manager, and model-provider secrets use KMS encryption.
- ECS task and Lambda roles use least privilege; no static AWS access keys are needed.
- RDS is private and reachable only from backend/worker security groups.
- Bedrock access is least privilege by model/action and environment.
- Audit logs, `query_audit_log`, `agent_trace_log`, `response_grade`, and `anomaly_flag` support investigation.
- PII/sensitive-output guardrails should be kept before response send and before cache writes.

## Environments and Configuration

Three environments, ideally as **separate AWS accounts** (blast-radius isolation is worth more than the account-management overhead), or at minimum separate VPCs, databases, secrets, and buckets.

| Environment | Purpose | Data | Model access |
|---|---|---|---|
| `dev` | Integration of merged work | Synthetic PDFs only | Cheap/fast model; low budget cap |
| `staging` | Release candidate; migration rehearsal; gold-eval runs | Production-like, de-identified | Same models as prod, lower quota |
| `prod` | Live | Real clinical documents | Full routing policy |

Configuration is environment-driven, never baked into images. Every setting in `backend/app/settings.py` is overridable by env var; secrets (`ANTHROPIC_API_KEY`, `JWT_SECRET`, `DATABASE_URL`, …) come from Secrets Manager/SSM at task start. Settings that **must** be changed from their local defaults before production:

- `ANONYMOUS_CHAT_ALLOWED=false` and a real `JWT_SECRET` — the local reviewer stack runs chat anonymously and document routes publicly (see Assumptions in the README); production must not.
- `CORS_ALLOWED_ORIGINS` — explicit origins only, never `*`.
- `ENABLE_SCHEDULED_JOBS` — on in exactly one environment per database, guarded by the advisory-lock singleton.
- `UPLOAD_STORAGE_BACKEND=s3` / `PAGE_IMAGE_STORAGE_BACKEND=s3` — container filesystems are ephemeral.
- `EMBEDDING_DIM` must match the deployed schema. Changing the embedding model is a **re-index**, not a config flip: the pgvector column is fixed-width and the semantic cache is scoped by `embedding_model` precisely so a model change cannot silently compare vectors across models.

## CI/CD Strategy

**The build/test half of this pipeline exists** in `.github/workflows/ci.yml` (jobs: `frontend`, `chainlit`, `backend`, `e2e`, gated by `verified`). **The deploy half does not** — there is no IaC and no target environment yet. The stages below marked *(planned)* are design; the rest are running today.

**Branching.** Trunk-based: short-lived branches into `master`, every merge is a release candidate. Tags cut releases; images are tagged with the commit SHA (never `latest`) so a rollback is an unambiguous pointer to a previously-passing artifact.

**Pipeline stages.** The important property is that **deploy is reachable only through explicit `needs:` gates** — a green deploy must be impossible while any check is red or skipped.

```
on PR ──────────────────────────────────────────────────────────────
  lint + typecheck        (ruff/mypy; tsc --noEmit; eslint)
  backend tests           (pytest, incl. migrations up/down + integration suite)
  frontend tests          (node --test)
  chainlit tests          (unittest)
  docker build            (backend + frontend + chainlit images build at all)
  migration check         (alembic upgrade head, then downgrade base, on a throwaway DB)

on merge to master ─────────────────────────────────────────────────
  ▸ all of the above         (needs: [...] — no bypass)
  ▸ build + push to ECR      (tag = git SHA)
  ▸ deploy dev               (terraform apply; migrate; smoke)
  ▸ e2e on dev               (Playwright against the deployed stack)
  ▸ deploy staging           (needs: e2e)
  ▸ gold-eval floor          (needs: staging — see gating caveat below)
  ▸ manual approval          (environment protection rule)
  ▸ deploy prod              (migrate → rolling deploy → smoke → auto-rollback on failure)
```

**Migrations are a separate, ordered step, not a container entrypoint.** Alembic runs as a one-off ECS task against the target database *before* the new image rolls out, and the deploy fails closed if it fails. Because rolling deploys briefly run old and new code together, migrations must be **backward-compatible**: add columns/tables in one release, backfill, and only drop in a later release once no running code reads them. Migration `0014` (adding `source_chunk_ids` to both cache tables) is an example of the safe shape — additive, with a default, so old code ignores it and new code populates it.

**Deployment strategy.** Rolling update on ECS with a health-check grace period and circuit breaker enabled, so a task that fails `/health` rolls back automatically. Blue/green via CodeDeploy is the upgrade path if a zero-downtime cutover with instant rollback becomes a requirement; it is not justified at current scale.

**Post-deploy smoke tests** (the deploy is not "done" until these pass): `/health` returns database-ok; `/docs` serves; a synthetic PDF uploads and reaches `indexed`; a chat question against that PDF returns a cited answer; a question outside it returns the no-answer. That last check is the one that catches a broken grounding path, which no unit test can catch in a live environment.

**Rollback.** Redeploy the previous task definition (previous image SHA). If a migration must be undone, restore from RDS point-in-time recovery — which is why migrations run in staging first and why a snapshot is taken before any destructive migration.

**Gold-eval gating caveat.** A score floor (`python -m gold_standard.runner --trigger ci --floor 85`) is designed for the pipeline, but **must not be enabled as a merge gate yet**: the corpus PDFs are not fetched or checksum-pinned and the expected answers are not human-verified, so the score it produces is not yet meaningful. Turning it on before that would be a gate that fails or passes for reasons unrelated to quality. It becomes a real gate once §Gold-Standard Evaluation's prerequisites are met.

**Supply chain.** Pin base images by digest; run `pip install` from a lockfile; scan images (ECR scanning or Trivy) and fail the build on critical CVEs; require signed commits on `master`.

## Secrets and API Key Management

Provider keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) are the highest-value secrets in this system: they are spendable. The posture below is what stops a leaked key from becoming an unbounded bill or a data-exfiltration path.

### The one structural decision

**Only the backend ever holds a provider key.** The browser never sees one, and there is no key in any frontend bundle — `frontend/.env.local.example` contains a base URL and nothing else. Both chat surfaces call `/api/v1/chat`; the backend makes every provider call server-side. This is why the Next.js app can be served as static assets from CloudFront without leaking anything: there is nothing in it to leak.

The corollary is that **no key may be prefixed `NEXT_PUBLIC_`**. Next.js inlines any `NEXT_PUBLIC_*` variable into the client bundle at build time — a key placed there is published to every visitor, and rotating it is the only remedy. Treat a `NEXT_PUBLIC_` provider key as an incident, not a bug.

### How keys are handled in code

| Property | How it is enforced |
|---|---|
| Read from the environment only | `os.getenv` at call sites; keys are never parameters that get logged, and are never persisted |
| Never written to the database | No key column exists. `query_audit_log` stores model name, tokens, and cost — not credentials |
| Never returned by the API | No route echoes configuration. `/api/v1/config/upload-limits` returns size/page/MIME limits only |
| Never logged | Provider selection logs the *variable name* and the fallback taken, never the value: `generation.provider_key_missing key=ANTHROPIC_API_KEY fallback=deterministic` |
| Never committed | `.env` is git-ignored; `.env.example` ships placeholders. A repo scan is part of the release checklist |
| Placeholders degrade safely | `_is_real_key` treats `your-anthropic-api-key-here` as *absent*, so an unedited `.env` selects the local fallback instead of 401-ing on every chat turn |
| Absence degrades, never crashes | Missing key → documented local fallback (see `.env.example`), plus a warning log. A provider outage returns the honest no-answer rather than a fabricated answer |

### Production injection

- **Store** in AWS Secrets Manager (preferred — supports rotation) or SSM Parameter Store as `SecureString`. Encrypt with a customer-managed KMS key so key access is independently auditable.
- **Inject at task start**, not at build. In ECS, reference the secret ARN from the task definition's `secrets` block so the value lands in the container environment and never appears in the task definition, the image, or CloudFormation output. **Never bake a key into a Docker image** — image layers are readable by anyone who can pull the image.
- **Never ship a `.env` to production.** It exists for local development only.
- **Scope the IAM task role** so the backend task can read *only* its own secret ARNs. Nothing else in the account should be able to read them.
- **No static AWS access keys.** S3 and Bedrock access come from the task/Lambda role.

### Rotation and blast radius

- Rotate provider keys on a schedule (90 days) and immediately on suspicion. Secrets Manager rotation plus a rolling ECS deploy makes this zero-downtime, because the key is read at task start.
- **Use a separate key per environment.** A dev key leaking must not spend production budget or reach production data.
- **Cap the blast radius at the provider**: set a spend limit on the API key at the provider console. IAM cannot bound spend on a third-party key — only the provider can. This is the control that turns a leaked key from an unbounded bill into a capped one.
- **Detect misuse**: AWS Budgets alerts plus the per-model cost tracking already in `query_audit_log` (`token_input`, `token_output`, `cost_usd`). A leaked key typically shows up as a cost anomaly before anything else, which is why cost anomaly detection is on the dashboard.
- **Scan for leaks in CI**: run a secret scanner (Gitleaks / GitHub secret scanning) on every PR and fail the build on a hit. Pre-commit hooks help but are not a control — they are advisory and can be skipped.

### What is deliberately *not* a secret

`MODEL_PRICING_JSON`, model IDs, retrieval tunables, and upload limits are configuration, not credentials. They live in plain environment variables so they can be changed without touching the secret store. `JWT_SECRET` **is** a credential — it must come from the secret store, and the `dev-only-change-me` default must never reach production.

## Observability and SLOs

The system already writes the data these need — `query_audit_log`, `agent_trace_log`, `response_grade`, `anomaly_flag`, and the `agentops_summary` view — so this is dashboards and alarms over existing tables, not new instrumentation.

| Signal | Target | Alarm |
|---|---|---|
| `/api/v1/chat` p95 latency | < 5s (cache miss), < 500ms (cache hit) | p95 > 8s for 10 min |
| 5xx rate | < 0.5% | > 2% for 5 min |
| Availability | 99.5% | two consecutive `/health` failures |
| Cache hit rate | > 30% steady-state | sustained drop (usually means cache invalidation is misfiring) |
| Grounding-failure rate | tracked, not fixed | sharp rise — a model or corpus change is producing ungrounded answers |
| Model spend | within budget | AWS Budgets + CloudWatch anomaly detection on cost |
| Gold-eval score | no regression | deviation alert vs. rolling baseline |

The two alarms that matter most for *this* system are the last three: they are the ones that catch the failure mode where the system is fully "up" and confidently wrong. Ordinary latency/5xx alarms would not fire at all in that scenario.

## Disaster Recovery

- **RPO ≤ 5 minutes**, **RTO ≤ 1 hour**, achieved with RDS automated backups plus point-in-time recovery, and S3 versioning for PDFs and page images.
- RDS Multi-AZ for automatic failover on instance/AZ loss.
- **Restore is rehearsed, not assumed**: a scheduled job restores the latest snapshot into a scratch database and asserts row counts and `alembic current`. An untested backup is not a backup.
- The database is the only stateful component. Application tasks are stateless and disposable; sessions, caches, audit, and grading all live in PostgreSQL, so recovery is a database recovery plus a redeploy.
- Uploaded PDFs are the one input that cannot be regenerated — S3 versioning plus cross-region replication for prod.

## Cost Model

At the assessment's scale (single-digit thousands of documents, low query volume), the floor is dominated by always-on infrastructure rather than model spend:

| Item | Driver | Control |
|---|---|---|
| RDS (Multi-AZ) | Always-on; the largest fixed cost | Right-size the instance; single-AZ in dev/staging |
| Fargate tasks | Backend + frontend + Chainlit baseline | Scale-to-low overnight in non-prod |
| Model calls | Per token, per model | Exact + semantic caches, prompt caching, and cheap-model routing for summaries/expansion/grading |
| S3 + CloudWatch | Volume of PDFs, page images, logs | Lifecycle rules; log retention limits |

The caches are a cost control, not just a latency control: an exact-cache hit costs zero tokens, which is why cache-hit rate is on the dashboard above. Ingestion cost scales with pages (OCR/rasterization), not with queries, so a large upload is a one-off spike rather than a recurring cost.

## Known Gaps and Open Items

Named rather than hidden, since none of this is deployed yet:

1. No IaC exists. Terraform (or CDK) for VPC, RDS, ECS, S3, IAM, Secrets Manager, ALB/WAF, and CloudWatch is the first build task.
2. No `.github/workflows/`. The pipeline above is a design, not a running system.
3. Ingestion is a FastAPI background task, not a durable queue. A restart mid-ingestion strands a document in `processing`. Replacing it with S3-event → SQS → worker is the first production-hardening change, and the document status guard is already idempotent enough to support it.
4. Gold-eval score floors are not trustworthy until the corpus is fetched, checksum-pinned, indexed, and expected answers are human-verified.
5. A clean-clone reproducibility run has not been performed.

## Migration and Data Strategy

- Alembic remains the database migration tool.
- Migrations should run in staging before prod.
- Production migrations should be backward-compatible where possible, especially for rolling deployments.
- Use RDS snapshots and point-in-time recovery before risky migrations.
- Keep uploaded PDFs and page images in S3, not container filesystems.
- Do not commit downloaded PDFs, generated gold reports, local database volumes, pycache, Playwright reports, secrets, or `.env`.
