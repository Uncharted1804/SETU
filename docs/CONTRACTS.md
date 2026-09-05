# CONTRACTS

The interfaces six people code against. `backend/app/contracts.py` is the source
of truth; this document explains it and adds the HTTP and event surfaces.

**Owner: P1. Changes are announced to everyone before they are committed.**

---

## 1. Conventions

These are the five questions everyone asks. Answered once.

| # | Convention | Rule |
|---|---|---|
| 1 | **Paths** | Every path crossing a boundary is a POSIX-style path RELATIVE to the workspace root (`data/workspace`), e.g. `uploads/scan_a1b2.pdf`. Absolute paths, drive letters and UNC prefixes are rejected. Clients download artifacts by `artifact_id`, never by path |
| 2 | **Identifiers** | `task_id` = `t_` + 12 hex, `session_id` = `s_` + 12 hex, `approval_id` = `ap_` + 12 hex, `artifact_id` = `a_` + 12 hex. All SERVER-GENERATED. A client may not choose one |
| 3 | **Pages and boxes** | Pages are 1-INDEXED. `bbox` is `[x0, y0, x1, y1]` in PDF points (72/inch), origin TOP-LEFT, with `x0 < x1` and `y0 < y1` — validated |
| 4 | **Confidence** | Always a float in `[0.0, 1.0]`, higher is better. Coding confidence is OBJECTIVE: exactly `1.0` iff `exit_code == 0`, enforced by a model validator |
| 5 | **Attempts vs iterations** | `Attempt.n` is 1-indexed, per STEP, bounded by `MAX_ATTEMPTS[agent]`. An ITERATION is one dispatched step, 1-indexed, bounded by `MAX_ITERATIONS`. **A retry consumes an attempt, never an iteration** |

**Terminal states** — `completed`, `failed`, `rejected`, `needs_human_review`,
`cancelled`. A task in one never runs again; this is what stops a duplicate
approval executing a task twice.
**Resumable** — `awaiting_approval` only.

**Errors.** Everything that fails crosses a boundary as a `StructuredError`
(`code`, `message`, `detail`, `retryable`). Tool exceptions are converted by the
dispatcher into an `Observation` with `ok=False` and emitted as an `error`
event — the loop continues so the planner can react. They are never unhandled
500s. Codes: `PATH_ESCAPE`, `NOT_FOUND`, `INVALID_ARGS`, `TOOL_FAILED`,
`SANDBOX_UNAVAILABLE`, `SANDBOX_TIMEOUT`, `MODEL_UNAVAILABLE`,
`NOT_IMPLEMENTED`, `APPROVAL_REQUIRED`, `APPROVAL_REJECTED`, `ITERATION_CAP`,
`LOW_CONFIDENCE`, `QUARANTINED`, `INTERNAL`.

---

## 2. The seven tools

Exactly seven, enforced by `ToolRegistry.__init__` in both modes and asserted by
`test_registry.py`. There is no `run_bash`, no HTTP tool, no email tool, no
`delete_file`, no dynamic import.

| Tool | Arguments model | Returns | Approval | Owner |
|---|---|---|---|---|
| `kb_search` | `KbSearchArgs{query, k≤20}` | `{query, chunks[Chunk], quarantined[Chunk], count}` | no | P3 |
| `read_file` | `ReadFileArgs{path, max_bytes}` | `{path, content, truncated, binary, bytes}` | no | P4 |
| `write_file` | `WriteFileArgs{path, content}` | `WriteResult{path, bytes_written, created, sha256}` | **yes** | P4 |
| `list_dir` | `ListDirArgs{path}` | `{path, entries[{name, path, is_dir, size_bytes}], count}` | no | P4 |
| `run_python` | `RunPythonArgs{code, timeout≤60, input_paths}` | `CodingOutput` | no | P4 |
| `sheet_op` | `SheetOpArgs{op, path, …}` | per-operation, see below | no | P6 |
| `docgen` | `DocgenArgs{kind, data, template?, out_name?}` | `{kind, artifact_id, path, size_bytes, sha256}` | **yes** | P6 |

Every handler receives a PARSED arguments model, never a raw dict — a malformed
model proposal fails validation before any code runs. Every argument model sets
`extra="forbid"`.

### `sheet_op` — one tool, four operations

| `op` | Requires | Rejects | Returns |
|---|---|---|---|
| `describe` | `path` | everything else | `{op, path, schema: SheetSchema}` |
| `read` | `path` | `spec`, `data`, `formatting`, `out_path` | `SheetRows` fields |
| `compute` | `path`, **`spec`** | `data`, `formatting`, `out_path` | `ComputeResult` |
| `write` | `path`, **`data`**, **`out_path` ≠ `path`** | `range`, `spec` | `{op, artifact_id, …WriteResult}` |

`describe` before `read` is the loop earning its keep: it lets the model reason
about a 400-row workbook without loading it into an 8k context. `write` never
overwrites its input — enforced by the type, not by convention.

### Approval semantics for write-capable tools

A tool marked `requires_approval` pauses execution and surfaces an
`ApprovalRequest` with `kind="write"` carrying `preview` — the ACTUAL content or
diff about to be committed — and `target_path`. Approving a filename is not
Layer 4.

---

## 3. Agents

An agent receives an `AgentInvocation` and returns an `AgentResult`. It does not
choose its model (the registry does), does not decide what runs next (the
orchestrator does), and never calls another agent (the orchestrator relays).

```
AgentInvocation{agent, model_id, model, prompt_summary, inputs, attempt, feedback}
        ↓
AgentResult{agent, model, payload, attempts[Attempt], final_confidence,
            needs_human_review, escalation_reason, error, simulated}
```

`inputs.prior` carries the last three observations — this is the relay: an agent
never reads another agent's output directly, the orchestrator hands it over as
data.

`feedback` is non-null on every attempt after the first and is recorded verbatim
in `Attempt.feedback_injected`, which is what lets the UI show
`attempt 2/4 · feeding failure back into the retry` and mean it.

| Agent | Capability | Threshold | Max attempts | Payload shape |
|---|---|---|---|---|
| `vision` | `vision` | 0.70 | 3 | `VisionOutput` |
| `reasoning` | `planning` | 0.65 | 3 | `ReasoningOutput` |
| `coding` | `code` | **1.00** | 4 | `CodingOutput` |

Coding's threshold is 1.00 because its signal is binary and objective. Coding
gets the extra attempt because a traceback tells the model precisely what to fix,
so a retry there has the highest expected value in the system.

---

## 4. The planner seam

```python
class Planner(Protocol):
    async def propose(task: TaskEnvelope, decision: RouterDecision) -> Plan
    async def next_step(plan: Plan, observations: list[Observation]) -> PlanStep | None
    def is_satisfied(plan: Plan, observations: list[Observation]) -> bool
```

Three rules for any implementation:

1. `next_step` MUST return the object that lives in `plan.steps`, never a copy —
   the executor mutates `step.status` and the UI renders `plan.steps` (D-016).
2. Every proposed step is validated by `PlanStep`, so a hallucinated tool name
   fails before anything runs.
3. Returning a step outside `plan.approved_scope` is allowed and expected — the
   executor will request a fresh approval for it.

---

## 5. HTTP routes

Base path `/api`. All of them are registered **before** `frontend/dist` is
mounted at `/`; reversing that order makes `/api/health` return `index.html`.

| Method | Path | Body / params | Returns |
|---|---|---|---|
| GET | `/api/health` | — | `HealthResponse{status, mock_mode, version}` |
| GET | `/api/ready` | — | `ReadinessResponse{ready, mock_mode, checks[]}` |
| POST | `/api/tasks` | `TaskCreateRequest{text, file_paths, session_id?, scenario?}` | 201 `TaskCreateResponse{task_id, session_id, state, stream_url}` |
| GET | `/api/tasks` | `?limit` | `TaskStatus[]` |
| GET | `/api/tasks/{task_id}` | — | `TaskStatus` |
| GET | `/api/tasks/{task_id}/stream` | `Last-Event-ID` header or `?last_event_id` | SSE |
| POST | `/api/tasks/{task_id}/approve` | `ApprovalDecision{approval_id, approved, note?}` | `{approval_id, approved, task_id, state}` — **409** on a duplicate |
| POST | `/api/tasks/{task_id}/cancel` | — | `{task_id, cancelled, state}` |
| GET | `/api/tasks/{task_id}/artifacts` | — | `ArtifactRef[]` |
| GET | `/api/tasks/{task_id}/artifacts/{artifact_id}` | — | the file (task-scoped; 404 across tasks) |
| POST | `/api/upload` | multipart `file` | `{path, original_name, stored_name, size_bytes}` |
| GET | `/api/network-status` | — | `NetworkStatus` |
| GET | `/api/models` | — | `ModelRegistryView` |
| GET | `/api/audit` | `?limit` | `{path, entries[AuditEntry]}` |
| GET | `/api/audit/verify` | — | `AuditVerification` |
| GET | `/api/mock/scenarios` | — | scenario list; **404 in real mode** |

`POST /api/tasks` with a `scenario` in real mode returns **400**. Fixtures never
silently activate against real components.

**Readiness never reports an unrun check as a pass.** A check that could not run
returns `skipped=true, ok=false`, and the UI must render that differently from a
tick.

---

## 6. SSE events

Envelope: `{type, data, seq, ts}`. `seq` is a per-task monotonic counter starting
at 1, also sent as the SSE `id:` field. The SSE `event:` name mirrors `type`.

> **Client trap (D-015):** because the server sets `event:`, a browser dispatches
> to `addEventListener(type, …)` and **not** to `onmessage`. Register a listener
> per type or the stream connects and delivers nothing.

### Blueprint event names — preserved exactly

| `type` | Emitted when | `data` |
|---|---|---|
| `route` | The router decides | `RouterDecision` |
| `plan` | A plan is proposed | `Plan` |
| `step_start` | A step begins | `{step: PlanStep, iteration, max_iterations}` |
| `token` | A model streams | `{text}` |
| `step_done` | A step completes | `{step_n, target, ok, confidence, summary, simulated, iteration}` |
| `attempt` | Any attempt of an agent step | `{step_n, agent, attempt, max_attempts, confidence, failure_reason, feedback_injected, simulated}` |
| `escalate` | Below threshold after the final attempt, or the iteration cap | `{step_n?, agent?, reason, attempts?, max_attempts?, code?}` |
| `artifact` | A file is produced | `ArtifactRef` |
| `audit` | Any audit entry is written | `AuditEntry` |
| `error` | Anything throws | `StructuredError` + `{step_n, target}` |

### Added by this scaffold (D-009)

| `type` | Emitted when | `data` |
|---|---|---|
| `state` | Task state transition | `{state, task_id}` (+ `mock_scenario`, `mock_mode` on creation) |
| `approval_request` | A human decision is required | `ApprovalRequest` |
| `approval_resolved` | A decision is recorded | `{approval_id, approved, kind}` |
| `quarantine` | Untrusted content is flagged | the quarantined `Chunk` |
| `done` | Terminal | `TaskResult` — **the stream closes after this** |

### Stream behaviour

- **Replay.** Up to 512 events per task are retained. A new subscriber receives
  everything it missed, then live events. This is what stops the browser losing
  `route` and `plan` to the subscribe-after-create race.
- **Resume.** `Last-Event-ID`, or `?last_event_id=N`, replays only `seq > N`.
- **Disconnect.** Closing the stream does NOT cancel or re-run the task. Only
  `POST /api/tasks/{id}/cancel` cancels.
- **Backpressure.** A subscriber that cannot keep up drops events rather than
  blocking the executor.

---

## 7. Mock mode

One setting: `SETU_MOCK_MODE` (default `1`). It diverges in exactly three places
— `build_agents`, `build_registry`, `build_planner` — and nowhere else. The
contracts, dispatcher, retry policy, approval flow, audit chain and SSE transport
are the same code in both modes.

Every simulated value is labelled: `AgentResult.simulated`, `ToolResult.simulated`,
`Observation.simulated`, `ArtifactRef.simulated`, and a `MOCK MODE` banner across
the top of the UI. `mock_run_python` reports `sandbox_available=false` and a
`<simulated - docker was not invoked>` command rather than pretending a container
ran.

Scenarios: `flagship`, `coding_retry`, `escalation`, `rejection`,
`observation_branch`, `observation_branch_clean`, `injection`.

---

## 8. Keeping the frontend in step

`frontend/src/types.ts` mirrors these models by hand and is verified by:

```bash
python scripts/check_contract_sync.py
```

It imports the Pydantic models directly (no server needed), compares field sets
for 15 interfaces and the members of the `EventType`, `TaskState`, `ToolName`
and `AgentName` unions, and exits non-zero on drift. **Run it before every
gate.** It is a check rather than a generator on purpose (D-014).
