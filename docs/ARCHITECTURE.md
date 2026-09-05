# ARCHITECTURE

How the modules that exist actually connect. This describes the code in this
repository, not the aspiration — where something is a seam, it says so.

---

## The three planes

```
┌──────────────────────────────────────────────────────────────────────┐
│  INTERACTION            frontend/src                                 │
│  App.tsx · task.tsx (banner, checklist, stream, artifacts)           │
│  proof.tsx (network, model registry, audit) · useTaskStream.ts       │
├──────────────────────────────────────────────────────────────────────┤
│  ORCHESTRATION          backend/app                                  │
│  router.py  →  orchestration/{planner, executor, dispatcher,         │
│                policy, approvals, events, state}                     │
├──────────────────────────────────────────────────────────────────────┤
│  EXECUTION              backend/app                                  │
│  agents/{vision, reasoning, coding} · tools/* · llm/ollama_client    │
│  security/{paths, audit, injection, netwatch, cors, integrity}       │
└──────────────────────────────────────────────────────────────────────┘
```

**The execution plane has no authority.** Agents do not decide what runs next.
Tools do not call each other. Everything routes through the orchestration plane,
which is the only component holding the plan. That is what makes the system
auditable and what makes a fourth agent a one-file change.

---

## Request flow, module by module

```
POST /api/tasks
  api/routes.py::create_task
    service.py::create_task
      state.py            new_task_id / new_session_id, TaskRecord created
      router.py           route_task(envelope, ModelRegistry) -> RouterDecision
      mocks/scenarios     select_scenario(...)          [mock mode only]
      planner.py          build_planner(settings, ...)  -> MockPlanner | ModelPlanner
    service.py::start
      events.py           emit `route`   ← BEFORE the runner starts, so a late
      audit.py            append router.decision          subscriber still sees it
      asyncio.create_task(executor.execute_plan(...))
  201 {task_id, stream_url}
```

```
executor.execute_plan
  planner.propose()                      -> Plan
  events.emit("plan") · audit
  approvals.ApprovalGate.open()          -> parks on an asyncio.Future
      ← POST /api/tasks/{id}/approve resolves it
      (no GPU held, event loop free)
  plan.approved_scope = scope_of(steps)

  for iteration in 1..MAX_ITERATIONS:
      step = planner.next_step(plan, observations)      ← the loop's whole point
      if step is None: break
      if not approvals.in_scope(step, plan):            ← revision outside scope
          request a fresh approval
      events.emit("step_start")

      if step.kind == "tool":
          if spec.requires_approval: approve the ACTUAL content
          dispatcher.run_tool(step, ToolContext)
              tools/registry.py  validate args -> handler
          -> ToolResult -> Observation
      else:
          for attempt in 1..MAX_ATTEMPTS[agent]:
              dispatcher.run_agent(step, iteration, attempt, feedback, inputs)
              events.emit("attempt") · audit (every attempt)
              policy.evaluate(agent, result, attempt)
                  pass      -> break
                  retry     -> feedback = policy.build_feedback(...)
                  escalate  -> events.emit("escalate"); needs_human_review
          -> AgentResult -> Observation

      events.emit("step_done") · emit("artifact") for anything produced
      if planner.is_satisfied(...): break
  else:
      escalate with policy.cap_message()   ← the cap is NOT a success

  _finalise() -> audit · emit("state") · emit("done")
```

Four properties worth defending:

1. **One dispatcher for agents and tools.** `dispatcher.py` does not branch on
   which agent. That is why a fourth agent is a registry entry.
2. **The plan is revisable.** `next_step(plan, observations)` can return
   something that was not in the original plan. A fixed list executed in order is
   a pipeline wearing a loop's clothes.
3. **A hard iteration cap of 5**, and reaching it ends the task
   `needs_human_review` — never `completed`.
4. **Every step is audited and emitted before the next one starts.** The UI
   checklist is a live render of the audit stream, not an animation.

---

## The relay principle

Vision never calls Reasoning. The orchestrator takes Vision's output, puts it in
`AgentInvocation.inputs.prior`, and calls Reasoning with it.

```
  ┌──────────┐  AgentResult  ┌──────────────┐  Observation   ┌────────┐
  │  VISION  │ ────────────► │  ORCHESTRATOR│ ─────────────► │   UI   │
  └──────────┘               └──────┬───────┘   (SSE)        └────────┘
                                    │ new invocation built from the payload
                                    ▼
                             ┌─────────────┐
                             │  REASONING  │
                             └─────────────┘
```

Adding a fourth agent means a new module, one line in `agents/__init__.py`, and a
new entry in `contracts.AGENT_NAMES`. **No existing agent is rewritten.**

---

## Where mock and real diverge

Exactly three call sites, all reached from `service.SetuService.build()`:

| Seam | Mock | Real |
|---|---|---|
| `agents.build_agents` | `MockAgent` × 3 | `VisionAgent`, `ReasoningAgent`, `CodingAgent` |
| `tools.registry.build_registry` | fixtures for `kb_search`, `run_python`, `sheet_op`; **real** fs and docgen | all real handlers |
| `orchestration.planner.build_planner` | `MockPlanner` (Scenario-driven) | `ModelPlanner` |

Everything downstream — contracts, dispatcher, policy, approvals, audit, events,
API — is the same code. That is the point: the mock exercises the real spine.

`build_planner` raises rather than constructing a `MockPlanner` when
`mock_mode` is false, and `POST /api/tasks` rejects a `scenario` in real mode
with 400. Fixtures cannot silently activate.

---

## Lazy loading

Nothing heavy is imported at module scope. `chromadb`, `sentence_transformers`,
`pymupdf`, `pytesseract` and `docx` are imported inside the function that needs
them (`tools/base.py::optional_import`), which is why a teammate with none of
them installed can still run the app and the entire test suite.

---

## The capability surface

Seven tools, enforced by `ToolRegistry.__init__` in both modes:

```
kb_search  read_file  write_file  list_dir  run_python  sheet_op  docgen
```

There is no shell tool, no HTTP tool, no email tool, no `delete_file` and no
dynamic import. **These absences are the architecture, not an oversight.** The
OCR cascade (`tools/ocr.py`) and the sandbox runner (`tools/sandbox.py`) are
internal services, not model-callable tools — adding them to the registry would
make the number in the pitch wrong.

`sheet_op("compute")` uses the same sandbox runner as `run_python`. That is a
shared implementation service, not a tool calling a tool: `sheets.py` imports the
runner directly, exactly as the `run_python` handler does.

---

## Security layers, and what each one actually covers

| Layer | Module | What it covers | What it does NOT cover |
|---|---|---|---|
| 1 Network isolation | `tools/sandbox.py` `--network=none` | The container has no interface | Says nothing about the host |
| 2 Sandbox hardening | `sandbox.build_command` | Nine controls on generated code | **Not the SETU backend**, see below |
| 3 No shell tool | `tools/registry.py` | Seven typed functions; none takes a command | — |
| 4 Human gate | `orchestration/approvals.py` | Plan, revision-scope and write approvals with content preview | A human who approves without reading |
| 5 Audit chain | `security/audit.py` | Selective edits are detectable | A full rewrite by an operator-level attacker |
| 6 Injection | `security/injection.py` | Tripwires, structural tagging, quarantine | **Not a complete defence.** Paraphrase and encoding evade regex |
| 7 Model integrity | `security/integrity.py` | *(scaffolded — nothing is verified yet)* | Currently nothing |
| 8 Same-origin | `main.py` + `security/cors.py` | No cross-origin request exists in the real deployment | — |
| 9 Classification | `scripts/netwatch_classifier.py` | Four buckets, configured membership only | A sampled zero is not an all-time zero |

### Host isolation is a deployment requirement, not a container flag

The nine sandbox controls isolate **generated code**. The SETU backend itself
runs on the host as an ordinary user process with read/write access to the
workspace and append access to the audit log. Do not claim the container flags
protect the host. A real deployment needs, at minimum:

- a dedicated service account with no interactive login,
- ACLs limiting that account to `data/workspace` (write) and `logs/` (append),
- the audit directory not writable by the account any tool can reach,
- the firewall rule scoped to the trusted subnet, and Ollama on loopback only.

The blueprint's reason for not containerising the orchestrator stands: it needs
the Docker socket to launch sandboxes, and mounting the socket into a container
would hand any compromise of the backend full control of the daemon.

### The path jail

One function, `security/paths.py::jail()`, used by every filesystem surface:
uploads, tool reads and writes, spreadsheet inputs, generated documents and
artifact downloads. It rejects absolute and drive-qualified paths up front, then
joins and `resolve()`s — resolving *after* joining is what catches a symlink
pointing out of the workspace, not just `../`. Uploaded filenames are never used
as path components; the server generates the storage name.

---

## The event bus

`orchestration/events.py` holds one `TaskEventStream` per task: a bounded deque
of 512 events plus a set of subscriber queues. A subscriber is replayed the
history it missed, then streamed live. `seq` is monotonic per task and is used as
the SSE `id:`.

This exists because execution starts as soon as `POST /api/tasks` returns, so
`route` and `plan` are normally emitted before the browser's `EventSource`
connects. Without the replay buffer the router banner and the approval checklist
never appear.

The store is in-memory and single-process. Restart recovery is out of scope
(D-007); there is no Redis and no Celery.
