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

## SECTION 0 — AUTHORITATIVE CURRENT-STATE CORRECTION

**Last reconciled:** 2026-09-06 by Codex, after inspecting the actual
repository and restoring the P5 development environment.

Sections 3–17 below are retained as an **initial historical snapshot only**.
They incorrectly describe the repository as empty and must not be used to make
implementation, ownership, contract, or readiness decisions. The authoritative
current state is:

- SETU is an implemented **integration scaffold**, not an empty repository.
  Read `docs/STATUS.md`, `docs/TEAM_HANDOFF.md`, and `docs/CONTRACTS.md` before
  claiming a component works.
- P5 (Mugdh) owns all of `frontend/`. The React/Vite/Tailwind mock-mode UI is
  implemented. It has durable, server-owned conversation history backed by
  SQLite and an HttpOnly session cookie; the chat-first research-ledger shell
  has attachment staging, collapsible plan/artifact evidence, history at left,
  and Network/Audit proof at right. Task, approval, SSE, audit, and API
  semantics remain unchanged.
- P5 Phase 0 Step 1 baseline is recorded at
  `.tmp/ui-baseline/2026-09-06/manifest.md`. The Network proof panel polls
  `/api/network-status` immediately on mount and every **500 ms**; this is a
  frontend-only cadence change with no API-contract impact.
- Host/project Python is **3.12.10** through `.venv\Scripts\python.exe`.
  Python 3.12.10 is the single source of truth for the host backend and virtual
  environment. The separate Docker sandbox intentionally remains
  `setu-sandbox:py311`.
- Node.js is **v24.15.0** and npm is **11.12.1** for the entire project.
- ChromaDB remains the local retrieval database (`chromadb==1.5.9`); no
  PostgreSQL source or dependency is present.
- Verified on 2026-09-06: `pip check`, critical backend imports,
  `scripts/check_contract_sync.py` (15 interfaces and 4 unions),
  `npm run typecheck`, and `npm run build` all passed. Same-origin FastAPI and
  all seven mock scenarios passed through the local HTTP API and SSE replay.
  The user accepted the Phase 0 manual browser-validation checklist as passed;
  screenshots were intentionally not captured and the browser run was not
  independently recorded. The full offline wheel cache proof, real-mode
  services, and hardware checks remain unverified.
- Current worktree changes are the intentional documentation alignment for the
  Python/Node/npm standards plus this reconciliation. Review them before commit.

**Current P5 objective:** The user selected the second UI direction. Its
implementation is complete pending direct browser visual review and handoff.

**P5 continuation document:** `context.md` was previously present but is not in
the current workspace. Use this file with the authoritative status/contracts
documents before resuming P5 work.

## SECTION 1 — PROJECT IDENTITY

- **Project name:** SETU
- **Hackathon context:** Yes
- **Problem Statement ID:** UNKNOWN — REQUIRES VERIFICATION
- **Problem Statement title:** UNKNOWN — REQUIRES VERIFICATION
- **Organization:** UNKNOWN — REQUIRES VERIFICATION
- **One-sentence description:** Sovereign, multi-model AI assistant running locally on organizational hardware to securely process confidential documents and generate deliverables.
- **Core goal:** To prove sovereignty by architecture, not by promise, via a local open-weight multi-agent system orchestrating tasks like OCR, reasoning, and coding without internet access.
- **Current phase:** P5 Phase 2 implementation - pending visual/browser review
- **Last updated timestamp:** 2026-09-06
- **Last updated by:** Codex

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
| Git | Status check | `git status` | PASSED | 2026-09-05 | Initialized and on branch `p5-frontend-mugdh` |
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

### 2026-09-06 — Codex (P5)
Changed:
- Committed the project-runtime/documentation alignment and Network 500 ms
  polling change as `98bf3bb`.
- Rebuilt the P5 frontend as a chat-first task workspace.
- Added local light/dark appearance preference, attachment staging, a labelled
  Add icon, optional Network/Audit disclosure drawers, and an empty task state.
- Removed Models and mock-scenario controls from the normal user-facing UI and
  removed model names from displayed route information.

Preserved:
- API shapes, SSE event subscriptions, task polling, approval semantics,
  audit evidence, and mock-mode truthfulness.

Tests:
- `npm run typecheck` - passed.
- `npm run build` - passed.
- `.venv\Scripts\python.exe scripts\check_contract_sync.py` - passed (15
  interfaces and 4 unions).

Status:
- IMPLEMENTED - browser visual validation and scenario-matrix regression remain.

## SECTION 16 — HANDOFF / CONTINUATION STATE

CURRENT OBJECTIVE: Validate and hand off the user-selected research-ledger chat
workspace.
CURRENTLY WORKING ON: The frontend has durable, server-owned session history
and a three-rail research-ledger layout: session history, conversation, and
proof. It keeps the existing light/dark control, attachments, collapsible plan
and artifact surfaces, and hides models/mock scenarios from the normal UI.
FILES BEING TOUCHED: `frontend/src/App.tsx`, `frontend/src/components/common.tsx`,
`frontend/src/components/task.tsx`, `frontend/src/components/workspace.tsx`,
`frontend/src/index.css`, `frontend/tailwind.config.js`, and this handoff.
WHAT IS WORKING: Existing task submission/upload, approval, SSE, artifact,
audit, and network surfaces are retained behind the redesigned layout. Session
history is stored server-side in local SQLite and active-session state is held
in a same-origin HttpOnly cookie; no Chrome local storage is required.
WHAT IS NOT YET VERIFIED: Direct browser visual rendering at desktop/mobile
widths, keyboard use, individual mock-scenario regressions through the new UI,
offline wheel cache, real-mode services, and hardware gates.
LAST VERIFIED COMMAND: `cd frontend && npm run typecheck; npm run build; cd ..; .\.venv\Scripts\python.exe -m pytest backend\tests -q; .\.venv\Scripts\python.exe scripts\check_contract_sync.py`
LAST VERIFIED RESULT: Typecheck/build passed; backend tests: 201 passed, 1 skipped; contract check reported 15 interfaces and 4 unions.
CURRENT BLOCKER: None. Browser visual validation is the next quality gate.
NEXT ACTION: Review the chat workspace in a browser (light/dark, keyboard,
mobile width, approval/write approval, and optional evidence drawers), then
run the mock scenario matrix before the Phase 2 handoff.
DO NOT CHANGE: Shared backend contracts or another owner's files without
coordination. Do not change the host Python 3.12.10, Node.js v24.15.0, npm 11.12.1, or
ChromaDB decisions without explicit user approval.
IMPORTANT CONTEXT: The old empty-repository claim is superseded by Section 0.

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

## SECTION 29 - LATEST P5 CHANGE

### 2026-09-06 - Codex (P5), research-ledger direction

Changed:
- Added durable server-owned session history with local SQLite storage and an
  HttpOnly same-origin cookie. Historical sessions, terminal task snapshots,
  artifacts, and bounded same-session context can be restored without browser
  local storage.
- Applied the user-selected second visual direction: bright sans-led reading
  canvas, dark history rail, compact right-side proof rail, restrained evidence
  accent, collapsible plan/artifacts, and the existing scroll-aware composer.

Preserved:
- Existing upload, task creation, SSE, approval, artifact download, network,
  audit, and contract behaviours. No required API payload was changed or removed.

Verification:
- `npm run typecheck` and `npm run build` passed.
- Backend tests: 201 passed, 1 skipped.
- Contract sync passed: 15 interfaces and 4 unions.
- Direct browser visual review remains unrecorded.

Runtime note (2026-09-06):
- Replaced the stale local development backend on port 8000 with the current
  application. `/api/sessions` now returns 200 and `/api/sessions/current`
  returns the expected 204 when no session cookie is present.

Environment note (2026-09-06):
- Verified Node.js `v24.15.0`; no Node.js installation or modification was
  needed. Ran `npx @framer/agent@latest setup` successfully. The setup
  installed two Framer skills under the user-level agent skill directories.

UI refinement (2026-09-06):
- Added in-memory collapsible desktop rails: history can also be toggled with
  `[`, and the proof rail has its own direct control. The responsive drawer
  behaviour remains unchanged on smaller screens.
- Moved the artifact disclosure control into a utility strip above the composer
  text area, leaving attachments and send actions in the lower action row.
- Reduced unnecessary panel treatment by relying on spacing and hairline
  dividers, while preserving visible focus, error, composer, and artifact
  affordances. No API or backend change was made.
- Re-verified `npm run typecheck`, `npm run build`, backend tests (201 passed,
  1 skipped), and contract sync (15 interfaces and 4 unions).

UI polish & layout refinements (2026-09-06 - Antigravity):
- Item 1: Removed `0.1.0-scaffold` version badge from header and updated `backend/app/config.py` VERSION to `0.1.0`.
- Item 2: Implemented auto-resizing composer textarea with Gemini-style height limit (max 160px), resetting cleanly on empty text, and added an Enlarge button (`Maximize2` icon) opening a dedicated expanded prompt modal dialog with char/word count and keyboard shortcuts (Ctrl+Enter to send, Esc to close).
- Item 3: Corrected "Message SETU" placeholder proportions and vertical alignment to be perfectly centered in the initial chat pill bar.
- Item 4: Elevated Plan approval decisions (`Approve` and `Reject`) from the bottom of the plan card into a top-level header pill group beside the Plan title, replacing the "4 steps" label when approval is pending.
- Item 5: Replaced the blinking orange reconnecting stream error box in the Activity stream with a quiet, smooth rotating loading icon in the Activity summary header.
- Item 6: Redesigned the Proof rail:
  - Fixed light mode and dark mode text visibility (high-contrast WCAG AA compliant across all labels, values, and prose).
  - Clear type scale: clean sans-serif for labels, prose, and action names; monospace strictly reserved for hashes, IDs, and digests.
  - Upgraded Network posture into a mini dashboard: bold external counter with status tint (emerald for 0 leaks), clean breakdown for loopback/trusted LAN.
  - Converted audit trail into an authentic connected timeline with vertical connecting lines and status dots.
  - Moved explanatory prose into distinctly styled info blocks with subtle backgrounds and info icons.
- Item 7: Harmonized into a single, cohesive design system across light and dark modes (Slate surfaces + Royal Blue primary action + Emerald/Amber/Rose semantic statuses).
- Verification:
  - `npm --prefix frontend run typecheck` passed (0 errors).
  - `npm --prefix frontend run build` passed.
  - `python scripts/check_contract_sync.py` passed (15 interfaces, 4 unions).
  - `pytest backend/tests` passed (201 passed, 1 skipped).
  - Direct browser verification completed and recorded with visual screenshots for all 7 items in both Light and Dark modes.

Network Posture Redesign (2026-09-06 - Antigravity):
- Replaced the oversized green "EXTERNAL 0 the number that matters" card with a balanced, informative socket telemetry dashboard:
  - Header: Live egress boundary state (`Air-gapped (Local only)` / `Active external egress`) with status indicator dot and total socket count (`X active sockets`).
  - Topology Distribution Bar: Visual proportional bar showing traffic distribution across loopback, WAN, LAN, and unclassified streams.
  - Symmetrical 2x2 Metric Grid: Uniform cards for External WAN, Loopback, Trusted LAN, and Unclassified with explicit socket counts, contextual sub-labels, and leak-detection status.
  - Preserved all honesty constraints: four numbers are never collapsed, blocked negative control attempts stay separate, and sampling scope disclaimers remain intact.
  - Removed redundant floating `Sovereign` badge from Network posture header, eliminating visual clutter.
- Neutral Plan Approval Option Pill:
  - Removed default pre-selected solid green highlight on `Approve` button to eliminate user confusion.
  - Rendered both `Approve` and `Reject` as neutral, equal unselected options inside the pill group.
  - Added subtle directional hover styling (emerald for Approve, rose for Reject).
  - Removed green highlight from `Air-gapped · 0 leaks` label, styling it with neutral `text-muted` to match other socket cards.
- Verification:
  - `npm --prefix frontend run typecheck`: 0 errors.
  - `npm --prefix frontend run build`: Clean production bundle.
  - Direct browser verification confirmed clean layout, correct typography, neutral unselected plan options, and proper active state on click.



