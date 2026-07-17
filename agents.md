# Multi-Agent Orchestration Protocol & AI Development Guidelines

This document defines the multi-agent framework, coordination workflows, and communication standards for all LLMs and AI agents operating in this codebase.

All development must proceed through the **Multi-Agent Build Loop** defined below. Under no circumstances may an agent perform unverified, unlogged, or direct edits to multiple components in a single unstructured pass.

---

## 1. Agent Directory & Roles

The team consists of five distinct, specialized roles. Each agent possesses a specific skill schema located in `/agents-skills/` or the root:

| Agent Name | Skill Spec Path | Primary Responsibilities |
|---|---|---|
| **Orchestrator** | `/agents.md` (This file) | Guides the overall development loop, parses build plans, initializes/closes build cycles, and dynamically updates the master `plan.md` progress file. |
| **Backend Engineer** | `agents-skills/Backend-engineer-SKILL.md` | FastAPI, Pydantic, PostgreSQL + pgvector schemas, Alembic migrations, secure REST endpoints, context compaction, API rate limiting, and exact/semantic caching. |
| **Frontend Engineer** | `agents-skills/Frontend-engineer-SKILL.md` | Next.js `/documents` upload/management UI, Chainlit streaming chat UI, client-side validation, citations, and live trace rendering. |
| **ML Engineer** | `agents-skills/ML-engineer-SKILL.md` | PDF chunking and embedding, HNSW vector indexing, cross-encoder reranking, multimodal table/figure detection, and nightly LLM-judge response grading. |
| **Test Agent** | `agents-skills/test-engineer-SKILL.md` | Implements and executes automated unit, integration, and E2E smoke tests for both backend and frontend. Owns and maintains the `tests-README.md` file. |
| **GitPR Agent** | `agents-skills/skills.md` | Manages git workflows, performs frequent descriptive commits following semantic guidelines, and authors professional, comprehensive Pull Request descriptions. |

---

## 2. The Multi-Agent Build Loop (The Cycle Lifecycle)

Every build cycle (from BC0 to BC20, as outlined in `/build-plans-architecture/BUILD_PLAN.md`) must strictly execute according to the following 5-phase loop:

```
┌─────────────────────────────────────────────────────────────┐
│             Phase 1: Ingestion & Planning                   │
│ (Read BUILD_PLAN.md -> Create/Update root plan.md)          │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│             Phase 2: Build Implementation                   │
│ (Skilled Agents implement code per their SKILL.md specs)    │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│             Phase 3: Testing & Verification                 │
│ (Test Agent writes/runs tests, updates tests-README.md)     │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│             Phase 4: Workflow Tracking & Commit             │
│ (GitPR Agent stages files, commits frequently, drafts PR)   │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│               Phase 5: Cycle Closure                        │
│ (Orchestrator updates plan.md, transitions to next cycle)   │
└─────────────────────────────────────────────────────────────┘
```

### Phase 1: Ingestion & Planning (Orchestrator)
1. **Analyze Master Plans:** Read `/build-plans-architecture/BUILD_PLAN.md` and `/build-plans-architecture/ARCHITECTURE (4).md` to understand the current Build Cycle (BC_x) objectives, preconditions, and deliverables.
2. **Read/Create `plan.md`:** Inspect the root `plan.md` file. If it does not exist, create it immediately.
3. **Initialize the Cycle:** Add or update the active build cycle entry in `plan.md`. Specify:
   - Cycle ID (e.g., `BC1`) and Objectives.
   - Files to be added/modified.
   - Expected Test Coverage goals.
   - Initial status: `[ ] In Progress`.

### Phase 2: Build Implementation (Skilled Agents)
1. **Adopt Skill Profile:** The Orchestrator hands off to the relevant skilled agent (Backend, Frontend, or ML) by loading their specific skill spec from `/agents-skills/`.
2. **Apply Industry Best Coding Practices:**
   - **Type Safety:** Use strict static typing (no `Any` or un-typed Python definitions; full TS type coverage).
   - **Error Fallbacks:** No unhandled errors. Tool failures must degrade gracefully to deterministic fallbacks (e.g., Ingestion failure falls back to conservative text extraction).
   - **No Hidden Logic:** Prioritize explicit composition and delegation over complex inheritance. Avoid reflection or prototype manipulation.
3. **Log Architectural Divergences:** If implementation requires diverging from `/build-plans-architecture/ARCHITECTURE (4).md`, the agent MUST immediately log the divergence and its technical reasoning in Section 18 ("Decision Log") of `ARCHITECTURE (4).md` as part of the same cycle.
4. **Handoff:** Upon completing the implementation, the skilled agent writes a **Handover Envelope** (see Section 3 below) documenting the changes.

### Phase 3: Testing & Verification (Test Agent)
1. **Adopt Test Agent Profile:** The Orchestrator loads `agents-skills/test-engineer-SKILL.md`.
2. **Write Automated Tests:**
   - Implement backend unit/integration tests (`pytest`) matching the cycle's deliverables.
   - Implement frontend component/hook tests (`Jest`/`RTL`) or E2E smoke tests (`Playwright`).
3. **Execute Verification:** Run the full test suite. Do not skip tests or suppress errors.
4. **Update `tests-README.md`:** Document any new test suites, command arguments, mocking patterns, or environment requirements.
5. **Handoff:** Compile test outputs and write the updated verification status into the **Handover Envelope**.

### Phase 4: Workflow Tracking & Commit (GitPR Agent)
1. **Adopt GitPR Agent Profile:** The Orchestrator loads `agents-skills/skills.md`.
2. **Descriptive Commits:** Group incremental changes into logical sub-tasks and make **frequent commits** with highly descriptive messages. Never make a single massive commit at the end of a cycle.
3. **Conventional Commits:** Use prefixes like `feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`, as specified in Section 22 of the architecture record.
4. **Stage Cleanly:** Stage only the specific files relevant to this build cycle. Avoid staging untracked temp files or unrelated configurations.
5. **Draft Pull Request:** Write a highly professional, detailed PR description outlining the background, implementation details, test verification, and design decisions.

### Phase 5: Cycle Closure (Orchestrator)
1. **Update `plan.md`:** Set the status of the current build cycle to `[x] Completed`. Record final file changes, verification run outputs, and PR branch reference.
2. **Document Progression:** Update relevant root files or readmes to reflect the new feature state.
3. **Transition:** Declare the current cycle closed and set the target for the next cycle.

---

## 3. Communication & Handoff Protocols (The "Handover Envelope")

To ensure clean execution and context preservation between agents during the build loop, agents must communicate using a structured **Handover Envelope**. 

When handing off control, the executing agent must append their handover block to a dedicated file named `.codex/handover.json` (or output it as a clearly formatted JSON block in the terminal logs). The schema for the handover payload is:

```json
{
  "from_agent": "backend-engineer",
  "to_agent": "test-engineer",
  "cycle_id": "BC2",
  "status": "implemented",
  "files_modified": [
    "backend/app/main.py",
    "backend/app/models.py"
  ],
  "implementation_summary": "Created pgvector-enabled 'chunks' and 'page_images' models, wired Alembic migration script for additive database schemas.",
  "divergences_logged": "None. Fully compliant with ARCHITECTURE (4).md §6.",
  "verification_requirements": "Test model instantiation, verify that content_tsv is generated automatically by PostgreSQL as a computed column, and test the Alembic migration up/down scripts."
}
```

The receiving agent MUST read this payload to guide their execution, ensuring no information, requirements, or design details are lost in transition.

---

## 4. Plan and Readme Synchronization Rules

On each build cycle, the following documents MUST be synchronized dynamically:
1. **`plan.md` (Root):** Updated *twice* per cycle (at start to mark `[ ] In Progress` with goals, and at end to mark `[x] Completed` with summary/files/PR).
2. **`tests-README.md` (Root):** Updated during Phase 3 whenever new automated tests are added or verification workflows are altered.
3. **`ARCHITECTURE (4).md` §18 (Decision Log):** Updated during Phase 2 *only if* the skilled agent makes an intentional architectural divergence from the spec.
4. **Main `README.md` (Root) or `local-setup.md`:** Updated during Phase 5 if any new endpoints, configuration variables, database migrations, or setup steps are introduced that change how a human reviewer runs the project.
