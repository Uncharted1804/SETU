# STATUS — what is real, what is mocked, what is scaffolded, what is unverified

Last updated 2026-09-05 by P1, after building the integration scaffold.

**Read this before telling anyone — teammate or judge — that something works.**
The categories mean:

| Category | Meaning |
|---|---|
| **REAL** | Implemented and covered by a test that actually ran |
| **MOCKED** | A deterministic fixture stands in. The contract, dispatcher, approval flow, audit path and SSE transport around it are real; the output is not |
| **SCAFFOLDED** | Typed interface, docstring and owner TODO. Raises a clear error in real mode. No implementation |
| **UNVERIFIED** | A claim that has never been checked on this machine. Not a pass |

---

## Correction to the blueprint's starting assumptions

The blueprint (Part 0.3, Part 7) states that `config.py`, `main.py`,
`security/cors.py`, `security/netwatch.py`, `scripts/netwatch_classifier.py`
already exist, are frozen, and are covered by **26 passing tests**.

**None of that was true in this repository.** Verified 2026-09-05:

| Blueprint claim | Actual state before this scaffold |
|---|---|
| `backend/app/config.py` ✅ exists | Did not exist — `backend/` held only `requirements.in` and `requirements-lock.txt` |
| `backend/app/main.py` ✅ skeleton | Did not exist |
| `security/cors.py` ✅ DONE, do not modify | Did not exist |
| `security/netwatch.py` ✅ DONE | Did not exist |
| `scripts/netwatch_classifier.py` ✅ DONE, single source of truth | Did not exist |
| 26 passing netwatch tests | `backend/tests/` did not exist. Nothing to run |
| `scripts/preflight.py`, `scripts/offline_check.py` ✅ exist | **True.** Both are real, substantial, and were left untouched |

Everything in the first six rows was **newly written by P1** to the behaviour the
blueprint specifies. Treat those files as a baseline that has never been reviewed
by their owner, not as previously-frozen code. P4 owns them from here.

---

## Backend

| Component | File | Status | Owner | Notes |
|---|---|---|---|---|
| Shared contracts | `app/contracts.py` | **REAL** | P1 | 30+ models, validated; conventions documented in the header |
| Config + thresholds | `app/config.py` | **REAL** | P1 | Startup assertions enforced and tested |
| Model registry | `app/config.py` + `config/models.yaml` | **REAL** | P1 | Reads the FROZEN YAML; no model tag appears in any other file |
| Entry router | `app/router.py` | **REAL** | P1 | 5 rules, deterministic mixed-attachment precedence |
| Tool registry | `app/tools/registry.py` | **REAL** | P1 | Exactly seven enforced in both modes |
| Agent registry | `app/agents/__init__.py` | **REAL** | P1 | Three agents; a fourth is one line + a module |
| Task lifecycle + store | `app/orchestration/state.py` | **REAL** | P1 | In-memory, bounded, single process |
| Executor (the loop) | `app/orchestration/executor.py` | **REAL** | P1 | Generic over steps; knows nothing about the flagship |
| Planner interface | `app/orchestration/planner.py` | **REAL** | P1 | `MockPlanner` real; `ModelPlanner` scaffolded |
| Dispatcher | `app/orchestration/dispatcher.py` | **REAL** | P1 | One path for agents and tools |
| Retry/confidence policy | `app/orchestration/policy.py` | **REAL** | P1 | Thresholds, attempt budgets, feedback construction |
| Approvals | `app/orchestration/approvals.py` | **REAL** | P1 | Plan, revision-scope and write gates; non-blocking |
| Events + SSE replay | `app/orchestration/events.py` | **REAL** | P1 | Bounded history, seq ids, Last-Event-ID resume |
| API routes | `app/api/routes.py` | **REAL** | P1 | All routes registered before the dist mount |
| App factory | `app/main.py` | **REAL** | P1 | Route order asserted by a test with a real dist present |
| Path jail | `app/security/paths.py` | **REAL** | P4 | Traversal, drive-qualified and resolved-symlink escapes blocked |
| Audit chain | `app/security/audit.py` | **REAL** | P6 | Canonical hashing, serialised appends, verification |
| Connection classifier | `scripts/netwatch_classifier.py` | **REAL** (new) | P4 | Four buckets; `ip.is_private` deliberately unused |
| Network monitor | `app/security/netwatch.py` | **REAL** (new) | P4 | Reports monitor failure rather than emitting zeros |
| CORS gate | `app/security/cors.py` | **REAL** (new) | P4 | Off by default, fails closed, never a wildcard |
| Injection scan/wrap | `app/security/injection.py` | **REAL** | P3 | Tripwires + structural tagging. **Not** a complete defence |
| Ollama transport | `app/llm/ollama_client.py` | **REAL, untested against a live server** | P1 | Loopback validated, GPU semaphore, no pulls. Never exercised against running Ollama in this scaffold |
| `read_file` / `write_file` / `list_dir` | `app/tools/fs.py` | **REAL** | P4 | Real in both modes — mocking a file read would hide the jail |
| `docgen` (docx, xlsx) | `app/tools/docgen.py` | **REAL** | P6 | Produces genuine openable files; templates/polish still to come |
| `docgen` (pptx) | `app/tools/docgen.py` | **SCAFFOLDED** | P6 | Cut-list item 3; raises NOT_IMPLEMENTED |
| `sheet_op` describe/read/write | `app/tools/sheets.py` | **REAL** | P6 | Real openpyxl; formatting is a TODO |
| `sheet_op` compute | `app/tools/sheets.py` | **SCAFFOLDED** | P6 | Sandbox runner exists; spec→script translation does not |
| `run_python` / sandbox | `app/tools/sandbox.py` | **REAL, UNVERIFIED** | P4 | Code written; **never executed against Docker on this machine** |
| `kb_search` | `app/tools/kb.py` | **SCAFFOLDED** | P3 | Search implemented against Chroma; `ingest()` raises. No corpus indexed |
| OCR cascade | `app/tools/ocr.py` | **SCAFFOLDED** | P2 | `cascade_plan()` is real logic; every extractor raises |
| Vision agent | `app/agents/vision.py` | **SCAFFOLDED** | P2 | Real path returns NOT_IMPLEMENTED with escalation |
| Reasoning agent | `app/agents/reasoning.py` | **SCAFFOLDED** | P3 | As above |
| Coding agent | `app/agents/coding.py` | **SCAFFOLDED** | P4 | As above |
| Model integrity | `app/security/integrity.py` | **SCAFFOLDED** | P6 | `integrity_verified` is `null` everywhere — never checked |

## Mock adapters (what each owner deletes)

| Mock | File | Replaced by | Owner |
|---|---|---|---|
| `MockAgent("vision")` | `app/mocks/adapters.py` | `agents/vision.py::VisionAgent` | P2 |
| `MockAgent("reasoning")` | same | `agents/reasoning.py::ReasoningAgent` | P3 |
| `MockAgent("coding")` | same | `agents/coding.py::CodingAgent` | P4 |
| `mock_kb_search` | same | `tools/kb.py::kb_search` | P3 |
| `mock_run_python` | same | `tools/sandbox.py::run_in_sandbox` | P4 |
| `mock_sheet_op` | same | `tools/sheets.py::sheet_op` | P6 |
| `MockPlanner` | `app/orchestration/planner.py` | `ModelPlanner` | P1 |

## Frontend

| Surface | Status | Notes |
|---|---|---|
| Prompt + upload | **REAL** | Uploads go through the jail with server-controlled names |
| Router banner | **REAL** | Model, reason, rule id, latency — proves R4 |
| Plan checklist + approve/reject | **REAL** | Ticks from `step_done`; write approvals show the actual content |
| Streaming execution log | **REAL** | Driven by SSE. No animation timers |
| Retry / escalation display | **REAL** | `attempt 2/4 · feeding failure back into the retry` |
| Artifact download | **REAL** | Task-scoped, opaque artifact ids |
| Network panel | **REAL** | Four separate counters, negative control on its own row, scope caveat on screen |
| Model registry panel | **REAL** | Renders unchecked digests as "digest not verified" |
| Audit viewer + verify | **REAL** | One click walks the chain |
| Token streaming display | **REAL surface, no producer** | The `token` event is handled; no agent emits one yet (P1/P3) |
| Visual polish | Minimal by design | Functional integration first |

## Checks actually run (2026-09-05)

| Check | Result |
|---|---|
| `pytest backend/tests -q` | **196 passed, 1 skipped** in ~12 s |
| `npm run build` (tsc -b && vite build) | **Passed**, 163 kB JS / 11 kB CSS |
| `python scripts/check_contract_sync.py` | **Passed** (caught and fixed one real drift on first run) |
| `python scripts/verify_audit.py` | **Chain intact**, 38 entries |
| `/api/health` returns JSON with `frontend/dist` mounted | **Passed** (test + live curl: `200 application/json`) |
| `/` serves `index.html` | **Passed** (live curl: `200 text/html`) |
| No CORS header by default | **Passed** (live `curl -I -H "Origin: ..."`) |
| Full flagship over live HTTP → downloadable DOCX | **Passed** — 4 steps, 37 592 bytes, valid OOXML |
| Flagship driven through the browser UI | **Passed** — banner, checklist, scope re-approval, SSE all render |
| 1 skipped test | `test_resolved_symlink_escape_is_blocked` — symlink creation needs privileges on this Windows host. Run it in an elevated shell or on WSL to confirm |

## Not run — do not report these as passing

| Claim | Why it is unverified | Owner | When |
|---|---|---|---|
| Windows firewall scoping is correct | Never executed on this laptop; `preflight.py` reports advisory-skip off Windows | P4 | T-3 |
| Ollama unreachable from a second device | Needs a second physical machine; the same-host check is only a precondition | P4 | T-3 |
| Sandbox actually executes code | `setu-sandbox:py311` was never run by this scaffold | P4 | H1–4 |
| Real Ollama inference works | No live call was made | P1/P2/P3/P4 | H1–4 |
| Model weights match their digests | Nothing computed a digest | P6 | H9–13 |
| Retrieval returns sane chunks | No corpus is indexed; `data/kb_corpus/` is empty | P3 | T-3 |
| LAN mode works end to end | Never launched with a trusted subnet on a real network | P4 | T-3 |
| The demo assets exist | `data/demo_assets/` holds two synthetic vision-bench PNGs only | P6 | T-3 |
