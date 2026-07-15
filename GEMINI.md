# Foundational AI Mandates — Read First

> **CRITICAL MANDATE FOR ALL AI AGENTS & LLMs:**
> This file is the canonical bootstrap and instruction file. You MUST read this file in its entirety before executing any script, running any commands, or modifying any code in this repository.

---

## 1. Multi-Agent Development Protocol

Development in this repository is strictly governed by a specialized, disciplined multi-agent architecture. You must act as a coordinated team of expert software engineers, ensuring perfect traceability, extensive testing, and high-quality revision tracking.

To fulfill this mandate, you must immediately read and adopt the **Multi-Agent Orchestration Protocol** defined in:
👉 **[`/agents.md`](./agents.md)**

---

## 2. Kernel Directives

1. **No Rogue Changes:** Never perform development or modifications in a single monolithic pass. You must proceed incrementally through well-defined **Build Cycles** specified in the build plans.
2. **Follow the Plans:** All architectural and implementation requirements must be grounded in the documentation inside `/build-plans-architecture/`:
   - [`ARCHITECTURE (4).md`](./build-plans-architecture/ARCHITECTURE%20%284%29.md) — The single source of truth for **what** to build and **why**.
   - [`BUILD_PLAN.md`](./build-plans-architecture/BUILD_PLAN.md) — The single source of truth for **in what order**, **who builds it**, and **what "done" means**.
3. **The `plan.md` Lifecycle:** Before beginning any implementation cycle, you MUST initialize or update the active progress state in:
   - `plan.md` (at the root of the project). This file tracks the active cycle, what is built, what tests are run, and what is completed. It is updated dynamically.
4. **Agent-Based Execution:** Implement code using the specialized skills in `/agents-skills/`:
   - `Backend-engineer-SKILL.md` (FastAPI, pgvector, schemas, retrieval)
   - `Frontend-engineer-SKILL.md` (Next.js, Chainlit UI, integration)
   - `ML-engineer-SKILL.md` (Chunking, reranking, multimodal gating)
   - `test-engineer-SKILL.md` (Test Agent — writes and executes automated tests for frontend/backend, manages `tests-README.md`)
   - `skills.md` (GitPR Agent — manages frequent commits, writes descriptive commit messages, and drafts professional PRs)
5. **Rigorous Verification:** No feature is considered built until the **Test Agent** has written and successfully run automated tests. You must document execution guidelines in [`/tests-README.md`](./tests-README.md).
6. **Descriptive Commits & Handoffs:** All development stages must follow the strict handoff protocol. The **GitPR Agent** must be invoked frequently to capture the development workflow using clear, descriptive commit messages and detailed Pull Requests.

---

## 3. Immediate Next Steps

1. **Load [`/agents.md`](./agents.md)** to configure your coordination loop.
2. **Consult `/build-plans-architecture/`** to analyze the active Build Cycle.
3. **Initialize [`/plan.md`](./plan.md)** to establish your current progress state and testing goals.
4. **Proceed incrementally**, respecting the handoff boundaries between specialized agents.
