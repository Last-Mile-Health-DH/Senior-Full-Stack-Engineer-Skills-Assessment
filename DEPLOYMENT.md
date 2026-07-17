# Production Deployment & Secrets Management Guide

This document outlines the production architecture, cloud deployment procedures, and security-first secret key management protocols for the **Last Mile Health RAG** system. It aligns with the specifications in Section 19 of [`ARCHITECTURE (4).md`](./build-plans-architecture/ARCHITECTURE%20%284%29.md).

---

## 1. Production Architecture Overview

The system is containerized, cloud-agnostic, and designed to scale horizontally. The concrete reference implementation targets **Amazon Web Services (AWS)** using managed, serverless, and isolated components:

```
                          ┌──────────────────────────┐
                          │   AWS Route 53 (DNS)     │
                          └────────────┬─────────────┘
                                       │
                                       ▼
                     ┌──────────────────────────────────┐
                     │  Application Load Balancer (ALB) │
                     └────┬────────────┬────────────┬───┘
                          │            │            │
             ┌────────────┘            │            └────────────┐
             ▼                         ▼                         ▼
 ┌───────────────────────┐ ┌───────────────────────┐ ┌───────────────────────┐
 │ Next.js Frontends     │ │ Chainlit Chat Services│ │ FastAPI Backend APIs  │
 │ (ECS Fargate Task)    │ │ (ECS Fargate Task)    │ │ (ECS Fargate Task)    │
 └───────────────────────┘ └───────────────────────┘ └───────────┬───────────┘
                                                                 │
                                       ┌─────────────────────────┼─────────────────────────┐
                                       ▼                         ▼                         ▼
                           ┌───────────────────────┐ ┌───────────────────────┐ ┌───────────────────────┐
                           │   RDS PostgreSQL 16   │ │    Amazon S3 Bucket   │ │  AWS Secrets Manager  │
                           │     (w/ pgvector)     │ │   (PDFs & Images)     │ │ (Injected at Runtime) │
                           └───────────────────────┘ └───────────────────────┘ └───────────────────────┘
```

### Infrastructure Components
1.  **Frontend & Chat Clients (Next.js & Chainlit):** Deployed as serverless container tasks on **AWS ECS Fargate** behind an Application Load Balancer (ALB).
2.  **RAG Backend (FastAPI):** Deployed on **AWS ECS Fargate**. The Dockerfile automatically provisions system-level `tesseract-ocr` and `poppler-utils` packages to support scanned PDF OCR and table page image rendering.
3.  **Database (Postgres 16 + pgvector):** Managed **Amazon RDS for PostgreSQL**. Deployed across multiple Availability Zones (Multi-AZ) with encrypted storage.
4.  **Object Storage (PDF & Images):** **Amazon S3** (Private Bucket). Uploaded PDFs and rasterized page images are stored here instead of on local container file systems. Page images are fetched by frontends securely using short-lived S3 pre-signed URLs.

---

## 2. Secrets Management Strategy (Zero-Leak Policy)

Hardcoded keys are strictly prohibited in this codebase. Production secrets must never be committed to Git, stored in docker images, or printed in application log traces.

### 2.1 Storage: AWS Secrets Manager
All active credentials and API tokens are stored securely in **AWS Secrets Manager** as a single JSON key-value secret (e.g., `production/last-mile-rag/secrets`).

### 2.2 Runtime Injection (ECS Integration)
Secrets are securely injected as environment variables into Fargate containers at boot time. This is defined natively in the ECS Task Definition using the `secrets` block, referencing the AWS Secrets Manager ARN and specific JSON keys:

```json
{
  "name": "ANTHROPIC_API_KEY",
  "valueFrom": "arn:aws:secretsmanager:us-east-1:123456789012:secret:production/last-mile-rag/secrets:ANTHROPIC_API_KEY::"
}
```

This ensures that:
- Secrets are **never** committed to version control.
- Secrets are **never** present in the Docker image layers.
- Application developers do not need access to production keys.

---

## 3. Critical Secrets Reference

The RAG application relies on the following credentials to operate. When deploying, ensure these exact variables are configured in the cloud secrets provider:

| Variable Name | Type | Purpose | Production Management |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Sensitive | API key for Claude 3.5 Sonnet / Haiku generation and agent loops. | AWS Secrets Manager (Task Injected) |
| `OPENAI_API_KEY` | Sensitive | API key for OpenAI text-embedding-3-small vectors. | AWS Secrets Manager (Task Injected) |
| `VOYAGE_API_KEY` | Sensitive | (Optional) Paired with Claude generation for Voyage Embeddings. | AWS Secrets Manager (Task Injected) |
| `JWT_SECRET` | Sensitive | A cryptographically secure 256-bit key used to sign Next.js/FastAPI session tokens. | AWS Secrets Manager (Task Injected) |
| `CHAINLIT_AUTH_SECRET` | Sensitive | A secure random signing key used by Chainlit to secure chat sessions. | AWS Secrets Manager (Task Injected) |
| `POSTGRES_PASSWORD` | Sensitive | Master password for the PostgreSQL vector database. | AWS Secrets Manager (Task Injected) |
| `DATABASE_URL` | Sensitive | Full DB connection string (includes user, password, host, port, DB name). | Constructed at launch time in task definition |

---

## 4. Production Deployment Steps

Follow this structured, step-by-step procedure to deploy the application to AWS:

### Step 1: Provision Infrastructure (Terraform)
Deploy the core VPC, Subnets, ECS Clusters, ALB, RDS instance, S3 Bucket, and Secrets Manager using Terraform:
```sh
cd terraform/
terraform init
terraform apply -var-file=production.tfvars
```

### Step 2: Seed Secrets
Populate AWS Secrets Manager with placeholders or actual API tokens via the AWS CLI or AWS Console:
```sh
aws secretsmanager create-secret \
  --name production/last-mile-rag/secrets \
  --secret-string '{"ANTHROPIC_API_KEY":"sk-ant-...","OPENAI_API_KEY":"sk-proj-...","JWT_SECRET":"supersecret","CHAINLIT_AUTH_SECRET":"chainlitsecret","POSTGRES_PASSWORD":"strongdbpass"}'
```

### Step 3: CI/CD Execution (GitHub Actions)
Our automated pipeline handles compilation, testing, building, and deployment when code is merged to `main`:
1.  **Linter & Tests:** Runs Python `ruff`, `pytest`, Next.js `eslint`, and Jest tests.
2.  **Docker Build & Push:** Builds container images and pushes them to **Amazon ECR** (Elastic Container Registry).
3.  **Task Definition Update:** Registers a new ECS task definition, injecting the Secret Manager ARNs for the environment variables.
4.  **Service Deployment:** Instructs ECS to perform a rolling blue-green deployment of the containers.

### Step 4: Run Database Migrations
Run the Alembic migrations against the production RDS database. This is executed as an ephemeral **ECS RunTask** immediately before the main backend service starts:
```sh
docker compose exec backend alembic upgrade head
# Or on ECS:
aws ecs run-task --cluster last-mile-rag --task-definition last-mile-rag-migrations
```

---

## 5. Security & Isolation Hardening (Best Practices)

1.  **Private Subnets:** Deploy all ECS container tasks and the RDS instance in private VPC subnets. Only the Application Load Balancer (ALB) should be exposed in public subnets.
2.  **IAM Least Privilege:** Create fine-grained IAM task execution roles. The FastAPI backend role should be granted permission to read/write *only* the specific RAG S3 bucket and decrypt *only* its specific Secrets Manager ARN.
3.  **S3 Access Control:** Disable "Block Public Access" selectively and only access S3 assets via IAM roles or short-lived pre-signed URLs. 
4.  **VPC Security Groups:** Restrict Postgres port `5432` access exclusively to incoming connections from the FastAPI backend's Security Group, completely isolating the DB from the public internet.
