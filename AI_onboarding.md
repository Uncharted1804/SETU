# SETU — AI ONBOARDING & LIVE PROJECT STATE

> [!IMPORTANT]
> ## AI BOOT PROTOCOL
>
> Before modifying ANY code:
>
> 1. Read `AI_onboarding.md`
> 2. Read applicable repository AI instructions
> 3. Check `git status`
> 4. Inspect the relevant files
> 5. Check ownership and active work
> 6. Check contract locks and known blockers
>
> After meaningful work:
>
> 7. Run appropriate tests
> 8. Update `AI_onboarding.md`
> 9. Verify that the document matches the actual repository
> 10. Review the final diff
>
> Never guess project state.
> Never silently change shared contracts.
> Never overwrite another owner's area without coordination.
> Never claim completion without evidence.

## SECTION 1 — PROJECT IDENTITY

- **Project name:** SETU
- **Hackathon context:** Yes
- **Problem Statement ID:** UNKNOWN — REQUIRES VERIFICATION
- **Problem Statement title:** UNKNOWN — REQUIRES VERIFICATION
- **Organization:** UNKNOWN — REQUIRES VERIFICATION
- **One-sentence description:** Sovereign, multi-model AI assistant running locally on organizational hardware to securely process confidential documents and generate deliverables.
- **Core goal:** To prove sovereignty by architecture, not by promise, via a local open-weight multi-agent system orchestrating tasks like OCR, reasoning, and coding without internet access.
- **Current phase:** Initial Setup / NOT_STARTED
- **Last updated timestamp:** 2026-09-05 22:57:21+05:30
- **Last updated by:** Antigravity (AI)

## SECTION 2 — WHAT SETU IS

SETU is a sovereign, self-hosted, multi-agent assistant designed to handle sensitive organizational knowledge work (e.g., approval notes, board decks, P&IDs) locally on mid-range GPU hardware (e.g., RTX 4060 8GB).

- **Sovereignty:** It is air-gapped by architecture. 
- **Models:** Uses multiple local open-weight models (Qwen2.5-VL 3B, Qwen2.5 7B Instruct, Qwen2.5-Coder 7B Instruct, BGE-small-en-v1.5) running on Ollama, loaded one at a time.
- **Orchestration:** 
  - **Router** chooses the entry model.
  - **Orchestrator** decides what happens next, loops, and relays information.
  - **Agents** specialize (Vision, Reasoning, Coding) but have no authority over the workflow.
  - **Tools** perform typed actions (a strictly allowlisted 7-tool capability surface).
- **Capabilities:** Multimodal (documents, handwriting), local RAG (Chroma embedded on CPU), sandboxed execution, real deliverables (Word/Excel/PPT).
- **Security Boundaries:** Path jail for file access, no shell tool, no generic network tool, hash-chained audit logging, same-origin frontend.

## SECTION 3 — ARCHITECTURE SNAPSHOT

### Intended Architecture (from Blueprint):
```
User
  ↓
Interaction Plane (Frontend, UI)
  ↓
Router (Rule-based entry selection)
  ↓
Orchestrator (Tool-calling loop, Planner)
  ↓
Agents (Vision / Reasoning / Coding) / Tools (7 allowlisted functions)
  ↓
Local Models (Ollama) / KB (Chroma) / Sandbox (Docker) / Deliverables
  ↓
Audit / Observability (Netwatch, Integrity)
```

### Current Implementation State (Actual):
- frontend: **NOT_STARTED**
- backend: **NOT_STARTED**
- FastAPI: **NOT_STARTED**
- Ollama: **NOT_STARTED**
- model registry: **NOT_STARTED**
- router: **NOT_STARTED**
- orchestrator: **NOT_STARTED**
- agents: **NOT_STARTED**
- tools: **NOT_STARTED**
- OCR: **NOT_STARTED**
- KB/RAG: **NOT_STARTED**
- sandbox: **NOT_STARTED**
- audit: **NOT_STARTED**
- network/security: **NOT_STARTED**
- deliverable generation: **NOT_STARTED**

> [!WARNING]
> The SETU Master Blueprint states that `config.py`, `main.py` and some security/script files exist. The actual repository currently contains NO Python files. Do not assume the spine is built.

## SECTION 4 — TEAM / ROLE OWNERSHIP

| Role | Owner | Responsibility | Main Files/Dirs | Current State |
|------|-------|----------------|-----------------|---------------|
| P1 | UNKNOWN | Orchestrator / Router / Tech Lead | `backend/app/main.py`, `backend/app/config.py`, `backend/app/router.py`, `backend/app/orchestrator.py`, `backend/app/llm/`, `backend/app/tools/registry.py` | NOT_STARTED |
| P2 | UNKNOWN | Vision / OCR Agent | `backend/app/agents/vision.py`, `backend/app/tools/ocr.py` | NOT_STARTED |
| P3 | UNKNOWN | Reasoning / Knowledge Base / Injection Defence | `backend/app/agents/reasoning.py`, `backend/app/tools/kb.py`, `backend/app/security/injection.py` | NOT_STARTED |
| P4 | UNKNOWN | Coding / Sandbox / Security / Infrastructure | `backend/app/agents/coding.py`, `backend/app/tools/fs.py`, `backend/app/tools/sandbox.py` | NOT_STARTED |
| P5 | Mugdh | Frontend / Observability | `frontend/` | NOT_STARTED |
| P6 | UNKNOWN | Deliverables / Audit / Demo | `backend/app/tools/docgen.py`, `backend/app/tools/sheets.py`, `backend/app/security/audit.py`, `backend/app/security/integrity.py`, `templates/`, `data/demo_assets/`, `scripts/verify_audit.py` | NOT_STARTED |

## SECTION 5 — FILE / DIRECTORY OWNERSHIP

The planned file structure and ownership is as follows (actual files do not exist yet):

- `backend/app/main.py` → P1
- `backend/app/config.py` → P1
- `backend/app/contracts.py` → P1 / SHARED
- `backend/app/router.py` → P1
- `backend/app/orchestrator.py` → P1
- `backend/app/llm/` → P1
- `backend/app/agents/vision.py` → P2
- `backend/app/agents/reasoning.py` → P3
- `backend/app/agents/coding.py` → P4
- `backend/app/tools/docgen.py` → P6
- `backend/app/tools/sheets.py` → P6
- `backend/app/tools/kb.py` → P3
- `backend/app/tools/ocr.py` → P2
- `backend/app/tools/fs.py` → P4
- `backend/app/tools/sandbox.py` → P4
- `backend/app/tools/registry.py` → P1
- `backend/app/security/audit.py` → P6
- `backend/app/security/integrity.py` → P6
- `backend/app/security/injection.py` → P3
- `frontend/` → P5
- `templates/` → P6
- `data/demo_assets/` → P6
- `scripts/verify_audit.py` → P6

## SECTION 6 — CURRENT IMPLEMENTATION STATUS

| Component | Owner | Status | Evidence | Dependencies | Next Action |
|-----------|-------|--------|----------|--------------|-------------|
| contracts | P1 | NOT_STARTED | No `contracts.py` | None | Define initial Pydantic schemas |
| main API | P1 | NOT_STARTED | No `main.py` | contracts | Create FastAPI app skeleton |
| router | P1 | NOT_STARTED | No `router.py` | contracts | Implement rule-based router |
| orchestrator | P1 | NOT_STARTED | No `orchestrator.py` | router, tools | Implement tool-calling loop |
| Ollama client | P1 | NOT_STARTED | No LLM integration | backend | Setup Ollama connection |
| model registry | P1 | NOT_STARTED | No `registry.py` | backend | Create model config |
| vision agent | P2 | NOT_STARTED | No `vision.py` | Ollama, OCR | Implement Qwen2.5-VL calls |
| OCR cascade | P2 | NOT_STARTED | No `ocr.py` | backend | Implement PyMuPDF/Tesseract cascade |
| reasoning agent | P3 | NOT_STARTED | No `reasoning.py` | Ollama, KB | Implement Qwen2.5 calls |
| coding agent | P4 | NOT_STARTED | No `coding.py` | Ollama, sandbox | Implement Qwen2.5-Coder calls |
| knowledge base | P3 | NOT_STARTED | No `kb.py` | backend | Setup ChromaDB |
| injection defence | P3 | NOT_STARTED | No `injection.py`| KB | Implement chunk validation |
| sandbox | P4 | NOT_STARTED | No `sandbox.py` | backend | Setup Docker execution env |
| filesystem jail | P4 | NOT_STARTED | No `fs.py` | backend | Implement path verification |
| sheet_op | P6 | NOT_STARTED | No `sheets.py` | sandbox | Implement sheet tools |
| docgen | P6 | NOT_STARTED | No `docgen.py` | backend, templates | Implement Word/PPT/Excel generation |
| audit | P6 | NOT_STARTED | No `audit.py` | backend | Implement hash-chain log |
| integrity | P6 | NOT_STARTED | No `integrity.py`| backend | Implement model verification |
| frontend | P5 | NOT_STARTED | No `frontend/` | API | Setup Vite |
| SSE | P5 | NOT_STARTED | No SSE endpoints | orchestrator | Implement streaming |
| network monitor | P5 | NOT_STARTED | No netwatch code | backend | Implement 3-way check |
| preflight | P1 | NOT_STARTED | No `preflight.py`| backend | Implement startup checks |
| demo assets | P6 | NOT_STARTED | No `data/` | None | Gather test files |
| templates | P6 | NOT_STARTED | No `templates/` | docgen | Create docx/pptx templates |
| tests | All | NOT_STARTED | No tests found | Codebase | Write initial unit tests |
| demo script | All | NOT_STARTED | No script doc | Demo assets | Finalize demo path |

## SECTION 7 — CONTRACT LOCKS

The 7-tool capability surface and SSE event structures are PLANNED. Because there is no code yet, all are unlocked. Once defined in `backend/app/contracts.py`, they MUST NOT be changed casually.

**Planned Tools (to lock):**
- `kb_search`
- `read_file`
- `write_file`
- `list_dir`
- `run_python`
- `sheet_op`
- `docgen`

**Planned SSE Events (to lock):**
- `route`, `plan`, `step_start`, `token`, `step_done`, `attempt`, `escalate`, `artifact`, `audit`, `error`

## SECTION 8 — ARCHITECTURAL DECISIONS

### ADR-001 — Model Ecosystem
- **Date:** Pre-hackathon (Blueprint)
- **Status:** APPROVED
- **Decision:** Use Ollama instead of vLLM. Load one model at a time.
- **Reason:** VRAM constraints (RTX 4060 8GB limit).

### ADR-002 — Routing & Orchestration
- **Date:** Pre-hackathon (Blueprint)
- **Status:** APPROVED
- **Decision:** Rule-based routing to select entry model; Orchestrator-owned sequencing.
- **Reason:** Predictability, speed, and auditability. The execution plane has no authority.

### ADR-003 — Restricted Execution Sandbox
- **Date:** Pre-hackathon (Blueprint)
- **Status:** APPROVED
- **Decision:** Narrow 7-tool surface. Path jail. No shell tool. No generic network/HTTP tool.
- **Reason:** Security; limit blast radius of prompt injections.

### ADR-004 — Same-origin Frontend
- **Date:** Pre-hackathon (Blueprint v2)
- **Status:** APPROVED
- **Decision:** Frontend served statically from the FastAPI backend in deployment.
- **Reason:** Eliminates CORS configuration risks.

### ADR-005 — Local Knowledge Base
- **Date:** Pre-hackathon (Blueprint)
- **Status:** APPROVED
- **Decision:** Chroma embedded KB running on CPU using `bge-small-en-v1.5`.
- **Reason:** Saves GPU VRAM for the primary models.

### ADR-006 — Hash-chained Audit
- **Date:** Pre-hackathon (Blueprint)
- **Status:** APPROVED
- **Decision:** Append-only hash-chained audit logging.
- **Reason:** Provable system actions for internal audit compliance.

## SECTION 9 — ACTIVE WORK

| Owner | Task | Files | Status | Started | Dependency | Notes |
|-------|------|-------|--------|---------|------------|-------|
| P1 | Initial Backend Setup | `backend/` | PLANNED | UNKNOWN | None | High priority. Need API & contracts. |
| P5 (Mugdh) | Initial Frontend Setup | `frontend/` | PLANNED | UNKNOWN | None | Setup Vite & API client |

## SECTION 10 — BLOCKERS

| Issue | Severity | Owner | Affected Area | Status | Workaround | Next Action |
|-------|----------|-------|---------------|--------|------------|------------|
| Missing Foundation | CRITICAL | P1 | Repo | ACTIVE | None | Initialize Git repository, create FastAPI and frontend skeletons |

## SECTION 11 — KNOWN BUGS / TECHNICAL DEBT

- **Issue:** Codebase is empty despite Blueprint v2 assuming `main.py`, `config.py` and 26 tests exist.
- **Severity:** HIGH
- **Owner:** P1
- **Impact:** Delays all dependent agents and frontend work.
- **Planned Fix:** Initialize the core backend structure immediately.

## SECTION 12 — TEST / VERIFICATION MATRIX

| Area | Test / Check | Command | Result | Last Verified | Notes |
|------|--------------|---------|--------|---------------|-------|
| Git | Status check | `git status` | FAILED | 2026-09-05 | Not a git repository |
| Codebase | Structure check | `ls -lR` | FAILED | 2026-09-05 | Source files missing |

## SECTION 13 — DEMO CRITICAL PATH

| Demo Beat | Status | Owner | Dependencies | Expected Result | Fallback |
|-----------|--------|-------|--------------|-----------------|----------|
| 1. startup/preflight | NOT_STARTED | P1 | Backend setup | Green checks | Hardcoded pass |
| 2. file upload | NOT_STARTED | P5 | Frontend, API | File accepted | Local load |
| 3. router decision | NOT_STARTED | P1 | Router | Rule selected | Forced route |
| 4. plan proposal | NOT_STARTED | P1 | Orchestrator | Steps listed | Hardcoded plan |
| 5. human approval | NOT_STARTED | P1/P5 | Orchestrator, UI| Proceed on click | Auto-approve |
| 6. vision extraction | NOT_STARTED | P2 | Vision Agent | Text extracted | Mock JSON |
| 7. KB search | NOT_STARTED | P3 | KB tool | Context retrieved | Static string |
| 8. reasoning | NOT_STARTED | P3 | Reasoning Agent | Draft generated | Mock text |
| 9. approval note generation | NOT_STARTED | P6 | docgen | docx saved | Simple txt |
| 10. spreadsheet describe | NOT_STARTED | P6 | sheet_op | Info returned | Mock dims |
| 11. spreadsheet read | NOT_STARTED | P6 | sheet_op | Rows returned | Mock rows |
| 12. spreadsheet compute | NOT_STARTED | P6 | sheet_op | Value returned | Basic math |
| 13. spreadsheet write | NOT_STARTED | P6 | sheet_op | xlsx saved | Local save |
| 14. coding agent | NOT_STARTED | P4 | Coding Agent | Python script | Pre-written code |
| 15. sandbox verification | NOT_STARTED | P4 | Sandbox | Script passes | Local exec |
| 16. retry | NOT_STARTED | P1/P4 | Orchestrator | Loop executed | Skip |
| 17. audit display | NOT_STARTED | P5/P6 | Audit, UI | Log visible | Static log |
| 18. audit verification | NOT_STARTED | P6 | Audit tool | Hash verified | Skip |
| 19. prompt-injection demonstration | NOT_STARTED | P3 | Injection Def | Defended | Skip |
| 20. network sovereignty proof | NOT_STARTED | P4/P5 | Netwatch | All internal | Disconnect WiFi |
| 21. model integrity proof | NOT_STARTED | P6 | Integrity | Hashes match | Skip |

## SECTION 14 — INTEGRATION NOTES

P1 → P5: Frontend expects `/api/health` and SSE endpoints.
P1 → All: Everyone depends on P1 to define `backend/app/contracts.py` before they can build their tools.

## SECTION 15 — RECENT CHANGES

### 2026-09-05 22:57 — Antigravity (AI)
Changed:
- Created `AI_onboarding.md`

Reason:
- To establish the shared project memory system.

Files:
- `AI_onboarding.md`
- `AGENTS.md` (updated to require reading this file)

Tests:
- None

Integration impact:
- All AIs must now read this file before modifying the codebase.

Status:
- Initialized

## SECTION 16 — HANDOFF / CONTINUATION STATE

CURRENT OBJECTIVE: Build the foundation (Git initialization, FastAPI, frontend skeleton)
CURRENTLY WORKING ON: Project initialization
FILES BEING TOUCHED: None yet
WHAT IS WORKING: The blueprint documentation is present.
WHAT IS NOT WORKING: Git is not initialized. No source code exists despite blueprint claims.
LAST VERIFIED COMMAND: `git status`
LAST VERIFIED RESULT: `fatal: not a git repository`
CURRENT BLOCKER: Git repository initialization and core structural setup.
NEXT ACTION: `git init`, create `backend/app/` and `frontend/`.
DO NOT CHANGE: The Blueprint files or AGENTS.md.
IMPORTANT CONTEXT: The repo is completely empty of source code. Disregard the blueprint's claim that `main.py`, `config.py`, and 26 tests exist. They must be written from scratch.

## SECTION 17 — NEXT SAFE ACTIONS

1. Initialize git repository (`git init`, `git add .`, `git commit -m "Initial commit"`).
2. Create `backend/app/contracts.py` and define the Pydantic schemas.
3. Create `backend/app/config.py`.
4. Create the `backend/app/main.py` FastAPI skeleton.
5. Create the `frontend` Vite app.

## SECTION 18 — AI RULES

RULE 1: Read `AI_onboarding.md` before coding.
RULE 2: Check `git status` before substantial work.
RULE 3: Assume other humans/AI agents may have changed the repository since your previous session.
RULE 4: Inspect actual files before editing them.
RULE 5: Respect ownership.
RULE 6: Do not modify another owner's area unnecessarily.
RULE 7: Do not silently change shared contracts.
RULE 8: Do not create duplicate functionality when an existing implementation may already exist.
RULE 9: Search before creating a new utility/class/function/service.
RULE 10: Do not introduce architectural changes casually.
RULE 11: Do not claim something is complete without evidence.
RULE 12: Do not fabricate test results.
RULE 13: Do not fabricate owner names.
RULE 14: Do not fabricate benchmark numbers.
RULE 15: Do not fabricate integration status.
RULE 16: When uncertain, explicitly write: `UNKNOWN — REQUIRES VERIFICATION`
RULE 17: When you discover a new architecture fact that future agents need, update `AI_onboarding.md`.
RULE 18: After meaningful work, update `AI_onboarding.md`.
RULE 19: Before finishing, compare `AI_onboarding.md` against the actual repository.
RULE 20: Review the final git diff before reporting completion.

## SECTION 19 — SHARED-FILE PROTECTION

For shared files (e.g., `contracts.py`, API schemas, central configuration, tool registry, orchestration interfaces):

An AI must:
1. Inspect current consumers.
2. Determine whether the change is breaking.
3. Avoid silent redesign.
4. Record the proposed change.
5. Explain integration impact.
6. Notify the human before making a breaking change.

## SECTION 20 — CHANGE DETECTION

When beginning a session:
Compare current repository state with what `AI_onboarding.md` says. Look for new files, deleted files, changed interfaces, new dependencies, and changed ownership. If the onboarding document is stale, update it before making new feature changes where practical. Never blindly trust yesterday's status.

## SECTION 21 — MULTI-AI CONFLICT HANDLING

If `AI_onboarding.md` contains conflicting information, DO NOT silently choose one.
Use: `CONFLICT — REQUIRES HUMAN RESOLUTION`
Explain the conflicting claims, affected files, likely source, and what must be verified. Never overwrite potentially important information merely to make the file look clean.

## SECTION 22 — HUMAN VS AI OWNERSHIP

The human developer remains responsible for architectural decisions. AI agents assist with implementation. Before making a substantial architecture change: explain the reason, identify impact, check ownership, check contract locks, and record the decision if approved.

## SECTION 23 — GIT BEHAVIOR

Use git to understand project state (`git status`, `git diff`, `git log`, `git branch`). Do not automatically commit unless explicitly instructed. Never claim a branch is merged unless verified. Never claim something is committed unless a commit exists.

## SECTION 24 — DO NOT PRETEND THIS IS MAGIC

This file relies on a chain of instructions. AI platforms are instructed to read this file via `AGENTS.md` (or similar). The onboarding document must reflect reality.

## SECTION 25 — AI SESSION WORKFLOW

SESSION START
    ↓
Read AI instructions
    ↓
Read `AI_onboarding.md`
    ↓
Check `git status`
    ↓
Inspect relevant files
    ↓
Check ownership
    ↓
Check active work
    ↓
Check blockers
    ↓
Check contract locks
    ↓
Plan changes
    ↓
Implement
    ↓
Test
    ↓
Update `AI_onboarding.md`
    ↓
Review diff
    ↓
Report exact result

## SECTION 26 — UPDATE GRANULARITY

Update `AI_onboarding.md` for meaningful events: feature started, feature completed, architecture changed, API changed, contract changed, blocker discovered/solved, major bug fixed, demo beat verified. Make surgical edits to preserve history.

## SECTION 27 — NO FALSE AUTOMATION

When authorship is unknown: `Owner: UNKNOWN`. 
When timing is unknown: `Started: UNKNOWN`. 
When verification is missing: `Status: IMPLEMENTED — NOT YET VERIFIED`.

## SECTION 28 — SETU-SPECIFIC SAFETY / ARCHITECTURE PRINCIPLES

1. Sovereign by architecture, not by promise.
2. The router selects the entry point/model.
3. The orchestrator decides sequencing.
4. Agents specialize.
5. Tools execute typed capabilities.
6. Execution components do not independently decide workflow.
7. The system intentionally has a narrow capability surface.
8. There is no arbitrary shell tool.
9. There is no generic network/HTTP tool.
10. Filesystem access is restricted to the allowed workspace.
11. Sandbox execution is isolated.
12. Retrieved documents are treated as data, not instructions.
13. Audit logging is append-only and hash chained.
14. Model integrity can be verified.
15. Multiple models may be registered while VRAM is managed carefully.
16. Frontend deployment is intended to use the backend's same-origin serving model.
17. Important sovereignty/security claims must be demonstrable, not merely written in documentation.
