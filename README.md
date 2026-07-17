## Last Mile Health — Senior Full-Stack Engineer, AI & Digital Health Practice Assessment

### Table of Contents
- [Technologies](#technologies)
- [Prototyping](#prototyping)
- [Running the app](#running-the-app)
  - [Docker Compose](#docker-compose)
  - [Backend (FastAPI)](#backend-fastapi)
  - [Frontend (React)](#frontend-react)
  - [Chat UI (Chainlit)](#chat-ui-chainlit)
- [Architectural decisions & trade-offs](#architectural-decisions--trade-offs)
  - [RAG Pipeline](#rag-pipeline)
- [Production deployment plan](#production-deployment-plan)
  - [App Infra](#app-infra)
  - [Proposed Production RAG Pipeline, support batch process at scale](#proposed-production-rag-pipeline-support-batch-process-at-scale)
- [Challenges](#challenges)
- [AOB](#aob)

### Technologies
- Postgres/Pgvector to store document vectors
- FastAPI
- React-router
- chainlit - for PoC chat 
- RAG
  - Semantic transformation to vectors - have used *SentenceTransformer* for this exercise
  > For Production, *Onnxruntime* transformer can be used because it is much lighter

### Prototyping
Prototyped on jupyter notebooks `notebook > RAGWorkflow.ipynb` the full RAG workflow. This enabled testing pdf parsing libraries, chunking and vectorization, and connection and querying on pgvector.
The full [RAG Pipeline](#rag-pipeline) is prototyped in the [notebook](notebook/RAGWorkflow.ipynb)

Once prototyping was done, code from the notebook was scaffolded into backend FastAPI, frontend and chainlit using Claude Code 

---

## Running the app

### Docker Compose

Backend, frontend, the Chainlit chat UI, and Postgres+pgvector all run as one stack — each service
builds from its own multi-stage Dockerfile (`backend/Dockerfile`, `frontend/Dockerfile`,
`chainlit/Dockerfile`):

```
cp .env.example .env
# edit .env: set OPENAI_API_KEY
docker compose -p assessment up -d --build
```

| Service | Tech | URL | Directory |
|---|---|---|---|
| Backend | FastAPI (Python, `uv`) | http://localhost:3000 | `backend` (package at `backend/app`) |
| Frontend | React + Vite + react-router (TypeScript) | http://localhost:8000 | `frontend` |
| Chat UI | Chainlit (Python, `uv`) | http://localhost:6100 | `chainlit` |
| Database | PostgreSQL + pgvector | `localhost:5432` | — |

`docker-compose.yaml` points `DATABASE_URL` at the `relational_db` container automatically — you only
need to supply the API key(s) in `.env`. It's loaded into the backend container via `env_file` at
runtime, never baked into the image (`.env*` is excluded via `.dockerignore`). Stop everything with
`docker compose -p assessment down`.

> Running the docker command can take upto ten minutes (specifically the chainlit container build)

### Backend (FastAPI)

```
cd backend
uv sync
uv run uvicorn app.main:app --port 6100 --reload
```

On startup it idempotently creates the "documents" table and an HNSW index if they don't already exist —
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
cd frontend
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
cd chainlit
uv sync
uv run chainlit run app.py --port 8000 -w
```

**Tests** (mocked HTTP calls, no live backend required):
```
uv run pytest
```

---

## Architectural decisions & trade-offs {#arch-tradeoff}
```mermaid
flowchart LR
    subgraph Clients
        U1[Admin / Private User<br/>Browser]
        U2[Public User<br/>Browser]
    end

    subgraph App["Docker Compose stack"]
        FE["Frontend<br/>React + Vite + react-router<br/>:3000"]
        CL["Chat UI<br/>Chainlit (Python)<br/>:8000"]
        BE["Backend API<br/>FastAPI (Python, uv)<br/>:6100"]
        DB[("Postgres + pgvector<br/>:5432")]
    end

    subgraph External
        OAI["OpenAI API<br/>(embeddings / chat completion)"]
    end

    U1 -->|HTTP| FE
    U2 -->|WebSocket| CL

    FE -->|"REST: POST /documents<br/>GET /documents<br/>GET /instructions"| BE
    CL -->|"REST: POST /chat<br/>(server-to-server via api_client.py)"| BE

    BE -->|psycopg / psycopg_pool| DB
    BE -->|"embed chunks<br/>(SentenceTransformer, local)"| BE
    BE -->|"chat completion"| OAI

    classDef frontend fill:#a3bffa,stroke:#2b4c8c,stroke-width:1px,color:#1a1a1a;
    classDef backend fill:#f6ad7a,stroke:#8c4a1a,stroke-width:1px,color:#1a1a1a;
    classDef storage fill:#8fd9a8,stroke:#1f6b3a,stroke-width:1px,color:#1a1a1a;
    classDef external fill:#e0e0e0,stroke:#555,stroke-width:1px,stroke-dasharray: 3 3,color:#1a1a1a;

    class FE,CL frontend;
    class BE backend;
    class DB storage;
    class OAI external;
```

**React-router**: Is light weight compared to NextJs, which is a full-stack framework

**React Frontend**: Used for document uploads. This combo handles files upload, and visual tracking of uploaded files. Frontend handles document upload through a drag-n-drop dropzone, which sends to the backend.

**FastAPI Backend**: The uploaded file goes through the full rag pipeline, that is, the file is loaded -> transformed using the sentence transformer -> chunked -> vectorized -> and saved to pgvector.
The backend also handles queries against the database, and integrates chatting with the LLM to produce comprehensive results. 

The full [RAG pipeline](#rag-pipeline) is captured below

**Chainlit**: Exposes the public facing chat UI 
In the implemented architecture, the frontend and backend layers are accessible to admins only; closed behind either a firewall or private network. The chainlit layer is public

**Pgvectors**: Stores document vectors, uploaded documents metadata and other persistent data

> These can be in a private network, not accessible to the public, whilst Chainlit is public.

##### RAG Pipeline
```mermaid
flowchart TD
    %% Styling Definitions
    classDef ingestion fill:#e8a8d8,stroke:#7a2e64,stroke-width:2px,color:#1a1a1a;
    classDef query fill:#a3bffa,stroke:#2b4c8c,stroke-width:2px,color:#1a1a1a;
    classDef storage fill:#f6ad7a,stroke:#8c4a1a,stroke-width:2px,color:#1a1a1a;

    %% Ingestion Phase (Data Preparation)
    subgraph Ingestion_Phase [Data Ingestion Pipeline]
        A[Raw Documents] --> B[Text Chunking]
        B --> C[Embedding Model]
        C --> D[(Vector Database)]
    end

    %% Query Phase (Retrieval & Generation)
    subgraph Query_Phase [User Query & Generation]
        E[User Query] --> F[Embedding Model]
        F --> G[Vector Search]
        
        %% Database Retrieval
        D -.-> |Retrieve Context| G
        
        G --> H[Combine Query + Context]
        H --> I[LLM Prompt]
        I --> J[Generated Response]
    end

    %% Apply Styles
    class A,B,C ingestion;
    class E,F,G,H,I,J query;
    class D storage;

```





## Production deployment plan

**Hybrid Search Pipeline using Agent**: Incorporate Hybrid search using Reciprocal Rank Fusion (RFF) for scoring on an agentic framework, building on the simple RAG pipeline. This would ensure robust results ranked by both text and vectors, with the *agentic loop* coming into play to ensure robust answers i.e. answers with additional queries automatically generated

**Ability to Create Knowledgebase**: Ability to create knowledgebase that bundle similar sources of information - in this case uploaded pdfs

**Litellm** - Wrap the LLM Api calls in litellm (An open gateway that unifies LLM APIs), which would enable quick switching between LLM providers

**Cloud provider**: AWS Backend and Chainlit as containerized services on Amazon Elastic Container Service(**ECS Fargate**), which is serveless compute infra, behind an Amazon Elastic Load Balance (**ALB**); frontend as a static build on **CloudFront**; database on **RDS for PostgreSQL** with the `pgvector` extension enabled, in a private subnet reachable only from the Fargate tasks.

**CI/CD** (using GitHub Actions):
- On every PR: lint + typecheck + test each service independently (`uv run pytest` for backend/chainlit,
  `npm test` + `tsc -b` for frontend) as a job; if fail, no deploy.
- On merge to `main`: build Docker images per service, push to (Elastic Container Registry) **ECR**, then update the corresponding
  ECS service; frontend build artifacts sync to **S3** with a CloudFront invalidation.
- Schema init already runs idempotently on backend startup, so no separate migration step is required for
  this scope — a longer-lived service would run migrations as an explicit pre-deploy step instead.

**Infrastructure considerations**:
- Secrets (`OPENAI_API_KEY`, `DATABASE_URL`, etc.) via **AWS Secrets Manager**, injected as task
  environment variables — never committed, never baked into images.
- `CORS_ORIGINS` set per-environment to the actual deployed frontend domain, not `localhost`.
<!--- `/health` semantics should move to "503 on DB-down" in production so both ALBs' target groups can
  actually route around an unhealthy instance.-->
- The `SentenceTransformer` embedder loads into memory once per instance at startup — size Fargate task
  memory accordingly and consider a minimum warm instance count to avoid cold-start latency on scale-out.
<!--- Connection pool size × number of backend replicas must stay under RDS's `max_connections`; add
  **PgBouncer** (or RDS Proxy) if the service scales beyond a handful of replicas.-->
- Structured logging + an error tracker (e.g. Sentry) wired into the existing global exception handler for
  production visibility beyond the current server-side traceback logging.

#### App Infra
```mermaid
flowchart TB
    subgraph Public["Public Internet"]
        PubUser["Public User<br/>Browser"]
    end

    subgraph AdminSide["Admin / Private Users"]
        AdminUser["Admin / Private User"]
        VPN["AWS Client VPN<br/>(SAML/OIDC federated)"]
        AdminUser --> VPN
    end

    subgraph AWS["AWS — VPC"]
        subgraph PublicSubnet["Public Subnets"]
            WAF["AWS WAF<br/>(managed rules + rate limiting)"]
            PubALB["Public ALB<br/>chat.example.org"]
            NAT["NAT Gateway"]
            WAF --> PubALB
        end

        subgraph PrivateSubnet["Private Subnets"]
            IntALB["Internal ALB<br/>(host-based routing)<br/>Route 53 private hosted zone"]

            subgraph FargateFE["ECS Fargate"]
                FE["Frontend<br/>React + Vite<br/>(nginx/serve)"]
            end
            subgraph FargateBE["ECS Fargate"]
                BE["Backend API<br/>FastAPI"]
            end
            subgraph FargateCL["ECS Fargate"]
                CL["Chainlit<br/>Chat UI"]
            end

            RDS[("RDS PostgreSQL<br/>+ pgvector")]

            IntALB --> FE
            IntALB --> BE
            FE -->|"/documents, /instructions"| BE
            CL -->|"ECS Service Connect<br/>(private, server-to-server)"| BE
            BE --> RDS
        end

        PubALB --> CL
        VPN -->|"private routing"| IntALB
        BE -->|outbound only| NAT
        CL -->|outbound only| NAT
    end

    subgraph Secrets["Secrets Manager"]
        SM["OPENAI_API_KEY<br/>DATABASE_URL"]
    end
    BE -.->|injected at task start| SM

    subgraph External["External"]
        OAI["OpenAI API"]
    end
    NAT --> OAI

    subgraph CICD["CI/CD — GitHub Actions"]
        GH["PR: lint/typecheck/test"]
        GH2["merge to main:<br/>build → push ECR → update ECS"]
        ECR[("Amazon ECR")]
        GH --> GH2 --> ECR
        ECR -.->|image pull| FargateFE
        ECR -.->|image pull| FargateBE
        ECR -.->|image pull| FargateCL
    end

    PubUser -->|"WebSocket (HTTPS)"| WAF

    classDef publicNode fill:#f6ad7a,stroke:#8c4a1a,stroke-width:1px,color:#1a1a1a;
    classDef privateNode fill:#a3bffa,stroke:#2b4c8c,stroke-width:1px,color:#1a1a1a;
    classDef storage fill:#8fd9a8,stroke:#1f6b3a,stroke-width:1px,color:#1a1a1a;
    classDef external fill:#e0e0e0,stroke:#555,stroke-width:1px,stroke-dasharray: 3 3,color:#1a1a1a;

    class PubALB,WAF,CL publicNode;
    class IntALB,FE,BE,VPN privateNode;
    class RDS,ECR storage;
    class OAI,SM external;
```

#### Proposed Production RAG Pipeline, support **batch processing** at scale
**note**: use of redis keystore for checks before queueing, and Apache Kafka for queue management

```mermaid

flowchart TD
    classDef ingestion fill:#e8a8d8,stroke:#7a2e64,stroke-width:2px,color:#1a1a1a;
    classDef queue fill:#f5c26b,stroke:#8c5a1a,stroke-width:2px,color:#1a1a1a;
    classDef cache fill:#7ec8e3,stroke:#1a5a7a,stroke-width:2px,color:#1a1a1a;
    classDef storage fill:#f6ad7a,stroke:#8c4a1a,stroke-width:2px,color:#1a1a1a;
    classDef query fill:#a3bffa,stroke:#2b4c8c,stroke-width:2px,color:#1a1a1a;
    classDef worker fill:#8fd9a8,stroke:#1f6b3a,stroke-width:2px,color:#1a1a1a;

    %% ---------------- Batch Upload / Ingestion ----------------
    subgraph Upload["Batch Document Upload"]
        A["Client<br/>(batch upload: N documents)"] --> B["Backend API<br/>POST /documents/batch"]
    end

    subgraph Dedup["Dedup Check"]
        B --> C{"For each document:<br/>compute content hash<br/>(e.g. SHA-256)"}
        C --> D["Redis Keystore<br/>EXISTS doc:hash?"]
        D -->|"Yes — already<br/>ingested or in-flight"| E["Skip document<br/>return existing status"]
        D -->|"No"| F["Redis SETNX<br/>doc:hash = QUEUED<br/>(atomic claim, prevents<br/>duplicate enqueue)"]
    end

    subgraph Queue["Kafka — Queue Management"]
        F --> G["Kafka Producer"]
        G --> H["Topic: document-ingestion<br/>(partitioned by doc hash)"]
        H --> I["Consumer Group:<br/>ingestion-workers<br/>(horizontally scalable)"]
        I -->|processing error<br/>after max retries| J["Topic: document-ingestion-dlq<br/>(dead-letter queue)"]
    end

    subgraph Worker["Ingestion Worker Pool"]
        I --> K["Extract text + page count<br/>(pdfplumber)"]
        K --> L["Chunk text"]
        L --> M["Embed chunks<br/>(SentenceTransformer /<br/>Onnxruntime)"]
        M --> N["Store chunks + vectors"]
        N --> O["Store document metadata<br/>(filename, size, pages, filetype)"]
        O --> P["Redis SET<br/>doc:hash = COMPLETED"]
        K -.->|failure| Q["Redis SET<br/>doc:hash = FAILED"]
        Q -.-> J
    end

    subgraph Storage["Postgres + pgvector"]
        N --> R[("document_chunks<br/>(vector column)")]
        O --> S[("document_files<br/>(metadata)")]
    end

    %% ---------------- Query Phase (unchanged) ----------------
    subgraph QueryPhase["User Query & Generation Pipeline"]
        T["User Query"] --> U["Embedding Model"]
        U --> V["Vector Search"]
        R -.->|Retrieve Context| V
        V --> W1["Combine Query + Context"]
        W1 --> W["Hybrid Search (RRF)"]
        W --> X["Agentic Loop/LLM Prompt"]
        X --> Y["Generated Response"]
    end

    class A,B,C ingestion;
    class D,F,P,Q cache;
    class G,H,I,J queue;
    class K,L,M,N,O worker;
    class R,S storage;
    class T,U,V,W,X,Y query;


```

---
### Challenges

The docker install threw me off since it was taking a non-trivial amount of time to install. 

> **Root cause:** the default repo chainlit docker image

Manually located the instructions file from 
<code>backend > app > home > routes.py</code>

locally (macos setup)
![local docker](locally.png)

On github codespace
![using github codespaces](codespaces.png)

### AOB
**note**: Go to `dev` branch to view individual commits

##### *now that you're here you can also checkout the [scrabble app](https://github.com/dakn2005/scrabble-realtime) on this repository; click on the title link to take to the live deploy hosted on render*
