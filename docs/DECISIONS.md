# DECISIONS

The blueprint is the architecture. It is also, in places, ambiguous or
self-contradictory — unavoidable in a document that size. This file records
every clarification made to turn it into running code, so nobody re-litigates a
choice at 3 a.m. and nobody is surprised by one.

Each entry: what was ambiguous, what was decided, and why.

---

### D-001 — The scaffold was built in `Desktop\setu`, not the empty working directory

**Ambiguity.** The session's working directory was an empty folder; the blueprint
and all existing work (`config/`, `scripts/`, `vendor/`, `.venv`,
`backend/requirements-lock.txt`) live in `C:\Users\shaur\Desktop\setu`.

**Decision.** Build in `Desktop\setu`.

**Why.** Scaffolding anywhere else would orphan a frozen model registry, a
hash-pinned lockfile, a cached wheel set, a built sandbox image and two real
scripts. Preserving existing work outranks matching a directory name.

---

### D-002 — The model registry stays Qwen3, not the blueprint's literal Qwen2.5 tags

**Ambiguity.** The blueprint's §2.3 router pseudocode, §2.5 agent sections and
§4.2 tables name `qwen2.5vl:3b`, `qwen2.5:7b-instruct-q4_K_M` and
`qwen2.5-coder:7b-instruct-q4_K_M`. `config/models.yaml` on this machine is
FROZEN to `qwen3-vl:4b`, `qwen3:8b` and `qwen2.5-coder:7b`.

**Decision.** The registry YAML wins. No model tag appears anywhere in Python.

**Why.** Three independent reasons point the same way. `ollama list` shows the
Qwen3 family installed and the Qwen2.5 vision tag absent — the blueprint's tags
would fail at runtime. `config/models.yaml` documents the substitution as a
benched, T-5-gated decision with real manifest digests, which §4.3 explicitly
permits. And the blueprint's own note appended to the router pseudocode says the
literal tags "do not exist on this machine and must not be copied verbatim" and
that `route_task()` must resolve tags from the registry at runtime. Requirement
R5 — "adding a model is a config change" — is only true if this holds.
`test_router.py::test_router_source_contains_no_hardcoded_model_tag` enforces it.

---

### D-003 — Python 3.12, not 3.11

**Ambiguity.** §5.1 pins Python 3.11. The existing `.venv` is 3.12.10 and
`requirements-lock.txt` was pip-compiled for 3.12.

**Decision.** Keep 3.12 on the host. The sandbox image stays Python 3.11.

**Why.** Regenerating a hash-pinned offline lockfile against a different
interpreter is a real risk for no benefit; nothing in the stack needs 3.11. The
container is a separate, already-built artifact and is unaffected.

---

### D-004 — Mixed attachments: vision wins

**Ambiguity.** The router rules are ordered but the blueprint never says what
happens when a PDF and an XLSX arrive in the same request.

**Decision.** Precedence, highest first: any vision-capable extension → vision;
else any spreadsheet extension → reasoning; else a code signal → coding; else a
deliverable signal → reasoning; else reasoning. Within a rule, the first matching
attachment in submitted order is reported as `matched_signal`.

**Why.** A page image cannot be read by any other agent, so skipping vision loses
information outright. A workbook is still reachable later through `sheet_op`
inside the loop, which is where spreadsheet work belongs anyway (R7). Submission
order therefore cannot change the routing decision — asserted in
`test_router.py::test_mixed_attachments_are_deterministic_and_vision_wins`.

---

### D-005 — The flagship is FOUR iterations, not two

**Ambiguity.** §2.4 says "express the flagship as two iterations of it" and the
Gate 2 test says "the plan checklist must show the flagship as *two* loop
iterations". §2.12 traces the same flow as four numbered iterations (vision,
kb_search, reasoning, docgen), §13.2 says "the flagship resolves to four of
them", and §14.3 asks for "≥ 2 loop iterations".

**Decision.** Follow the explicit four-step trace. `MAX_ITERATIONS` stays at 5.

**Why.** §2.12 is the concrete trace and §13.2 is the spoken claim; the "two"
references read as shorthand from an earlier draft, and §14.3's "≥ 2" is
satisfied by four. Four steps fit inside the cap, so the demo does not require
raising it — which matters, because raising a safety limit to fit a demo is
exactly the move that turns a bound into decoration.

---

### D-006 — Iterations count dispatched steps; retries do not consume one

**Ambiguity.** The blueprint caps iterations at 5 and attempts per agent at 3–4,
without saying whether a retry burns an iteration.

**Decision.** An ITERATION is one dispatched step (bounded by `MAX_ITERATIONS`=5).
An ATTEMPT is one try of a single step (bounded by `MAX_ATTEMPTS[agent]`).
Retrying a step consumes an attempt, never an iteration. Both are 1-indexed.

**Why.** The alternative makes the coding agent's 4-attempt budget unusable
inside a 5-iteration cap — one retried coding step would consume most of the
task. It also matches the blueprint's own arithmetic: the flagship is four
iterations *and* may retry within them.

---

### D-007 — In-memory task store; restart recovery is out of scope

**Ambiguity.** The blueprint rejects Redis and Celery but never says what happens
to a task when the backend restarts.

**Decision.** One bounded in-memory dict, single process. A restart loses
in-flight tasks. Documented in the README's limitations, not hidden.

**Why.** SETU is one operator on one workstation. Adding a broker would add a
service to the sovereignty story for no user-visible benefit.

---

### D-008 — Approval scope, and what a revision requires

**Ambiguity.** The blueprint requires plan approval before execution and says the
plan is revisable, but does not say whether a revised step needs fresh approval.

**Decision.** An approved plan records `approved_scope`, the set of
`kind:target` pairs the human actually saw. A revised step whose pair is not in
that set pauses execution for a fresh decision. Separately, every write-capable
tool (`write_file`, `docgen`) requests its own approval carrying the ACTUAL
content about to be committed.

**Why.** Approving "vision, then kb_search" is not consent to run `write_file`,
and approving a filename is not review of a document. Both are demonstrable on
stage: the `observation_branch` scenario asks a second time when the loop
inserts a `kb_search` nobody approved.

---

### D-009 — Added SSE event types beyond the blueprint's ten

**Ambiguity.** §6.1 lists ten event types. Several UI states have no event.

**Decision.** All ten names are preserved exactly. Five are added:
`state` (task transition), `approval_request`, `approval_resolved`,
`quarantine`, `done` (terminal; the stream closes after it). The envelope stays
`{type, data}`, plus a `seq` used as the SSE `id:` for ordering and replay.

**Why.** Without `done` a client cannot tell a finished stream from a stalled
one; without `approval_request` the gate is invisible to a late subscriber.
Documented in `docs/CONTRACTS.md`.

---

### D-010 — Bounded per-task event history

**Ambiguity.** The blueprint's flow POSTs a task then opens the SSE stream.
Execution starts immediately, so `route` and `plan` are usually emitted before
the browser connects.

**Decision.** Every task keeps up to 512 events; a new subscriber is replayed
what it missed, then streamed live. `Last-Event-ID` (and a `last_event_id` query
parameter) resume from a given seq.

**Why.** Without it the router banner and the approval checklist simply never
appear — a lost race that looks exactly like a broken UI.

---

### D-011 — Filesystem tools are real in mock mode

**Ambiguity.** "Mock mode" could mean every tool returns a fixture.

**Decision.** `read_file`, `write_file`, `list_dir` and `docgen` are real in both
modes. Only the components requiring a GPU, Docker, Tesseract or an embedding
model are mocked.

**Why.** Mocking a file read would hide the path jail, which is the thing the
jail exists to demonstrate. And a `docgen` that returns a fake path leaves the
download route untested until the demo — the mock flagship therefore produces a
genuine 37 kB DOCX.

---

### D-012 — `sheet_op` arguments are declared, not `**kwargs`

**Ambiguity.** §2.8 gives the signature as
`sheet_op(op, path, **kw)`.

**Decision.** One tool, four operations, with every operation's arguments
declared on `SheetOpArgs` and cross-validated: `compute` requires `spec`;
`write` requires `data` and an `out_path` that differs from `path`; each
operation rejects arguments belonging to another.

**Why.** An unvalidated public interface is precisely the teammate guesswork the
contracts file exists to remove, and "never overwrites an input" is a safety
property better enforced by the type than by a convention in prose.

---

### D-013 — Audit logs argument DIGESTS, not argument content

**Ambiguity.** §12.2 shows `args_hash` but the blueprint also says to log enough
to follow the sequence.

**Decision.** Task, session, action, model, step, iteration and attempt are
logged in the clear. Arguments are logged as a SHA-256 digest.

**Why.** Otherwise a scanned inspection report or a vendor's pricing schedule is
copied wholesale into a file with a different retention policy from the
workspace. The digest still proves the arguments were not altered after the fact.
Asserted by `test_audit.py::test_arguments_are_digested_not_copied`.

---

### D-014 — Frontend types are CHECKED against the backend, not generated

**Ambiguity.** The blueprint requires contract agreement but specifies no
mechanism.

**Decision.** `frontend/src/types.ts` is hand-written and verified by
`python scripts/check_contract_sync.py`, which imports the Pydantic models
directly and compares field sets and literal unions.

**Why.** A generator would rewrite P5's file on every backend edit and hide the
moment the two diverged; the team needs a loud failure at the gate instead. It
also avoids installing a codegen toolchain on six machines. It works: the first
run caught a genuinely missing `route_confidence` field.

---

### D-015 — Named SSE events require named listeners

**Ambiguity.** None in the blueprint — this is an implementation trap worth
recording because it cost real debugging time.

**Decision.** The server sets `event: <type>` on every SSE message, so the
browser dispatches to `addEventListener(type, ...)` and NOT to `onmessage`. The
hook registers a listener per type.

**Why.** With only `onmessage`, the stream connects successfully and delivers
nothing — indistinguishable from a broken backend. Found by driving the built UI
in a browser, not by the test suite.

---

### D-016 — The planner returns the plan's own step objects

**Ambiguity.** None stated — another implementation trap.

**Decision.** `Planner.next_step()` must return the object that lives in
`plan.steps`, never a copy. `_renumber()` keeps `n` equal to position after a
revision inserts a step.

**Why.** The executor mutates `step.status`, and the UI renders `plan.steps`.
Returning a copy meant every step stayed `pending` on screen forever while the
task completed normally — a silent, demo-fatal bug. Now asserted by
`test_orchestrator.py::test_the_checklist_reflects_step_status`.

---

### D-017 — Scenario selection matches whole words

**Decision.** `select_scenario()` uses word-boundary matching.

**Why.** `"spec" in text` also matches "in**spec**tion", which routed every
inspection-report demo to the spreadsheet scenario. Caught by driving the UI.

---

### D-018 — The sandbox image runs `main.py` directly

**Ambiguity.** §12.1's command ends `python:3.11-slim", "timeout", "15", "python", "main.py"`.

**Decision.** The command targets `setu-sandbox:py311`, whose `ENTRYPOINT` is
`["python", "-B"]`, and passes `main.py`. The wall-clock limit is enforced by the
caller with `asyncio.wait_for`.

**Why.** The hardened image deliberately strips coreutils, so `timeout` does not
exist inside it — and `python:3.11-slim` lacks openpyxl, which is why
`sandbox/Dockerfile` exists at all. Enforcing the timeout host-side also means a
hung container is killed even if its entrypoint is wedged.

---

### D-019 — `ModelPlanner` prompts the reasoning MODEL, not `ReasoningAgent`

**Ambiguity.** `planner.py`'s docstring said a real planner works "by prompting
the reasoning agent with the accumulated observations and the tool schemas."
That reads two ways: call `agents.get("reasoning").run()` (P3's `ReasoningAgent`
class), or call `llm/ollama_client.py` directly with the `planning` capability
resolved from `config/models.yaml`.

**Decision.** The latter. `ModelPlanner` owns its own prompt and calls the
transport directly. It never touches `agents/reasoning.py`.

**Why.** Three independent reasons, any one of which settles it:

1. `agents/base.py` states the agent contract outright — agents "DO NOT ...
   decide what runs next." Deciding what runs next is the planner's entire job,
   so routing planning through an agent would break the contract that makes a
   fourth agent cheap to add.
2. The shapes do not fit. An agent takes an `AgentInvocation` and returns an
   `AgentResult` carrying a confidence and an escalation reason — built to draft
   the *content* of one step. A planner needs a `Plan`, which is a different
   question at a different altitude.
3. It is not currently callable anyway. `ReasoningAgent.run()` opens with
   `self.ctx.registry.resolve("reasoning")`, and `"reasoning"` is an *agent*
   name, not a capability — `ModelRegistry.resolve` raises
   `ConfigError: unknown capability 'reasoning'` before reaching its
   `NOT_IMPLEMENTED` result. (P3 owns that line; `resolve_for_agent("reasoning")`
   or `ctx.model_for("reasoning")` is what it wants. Not changed here.)

A planner built on (1) would also have made `ModelPlanner` untestable and
unusable until P3's agent landed, coupling two owners' work for no reason.

**Second ambiguity, same docstring.** It also said `propose` uses
`registry.schemas()` for the seven tool schemas. But `service.py` calls
`build_planner(self.settings, scenario_key, self.agents, self.models)` — the
`registry` argument is the **`ModelRegistry`**, which has no `schemas()`. The
tool schemas live on `ToolRegistry`, a different object that is not passed in.

**Decision.** `ModelPlanner` builds its own `ToolRegistry` lazily via
`build_registry(self.settings)` and caches it.

**Why.** The alternative — widening `build_planner`'s signature and the
`service.py` call site to pass the tool registry too — is cleaner in the long
run, but `service.py` and `tools/registry.py` are shared files and that change
has to be announced first (CONTRIBUTING §1). `build_registry` is a pure factory
with lazy imports and no side effects, so constructing one inside the planner
costs nothing and keeps the resolution in a single owner's file. Revisit if the
planner ever needs the tool *handlers* rather than just their schemas.

---

### D-020 — `think=False` is hardcoded at the planner's call site, not read from the registry

**Ambiguity.** `config/models.yaml` declares `thinking: false` for
`reasoning-primary`, with the comment "on only for plan/tool choice if latency
permits". That reads as a configured, registry-driven setting. It is not one:
`ModelEntry` in `contracts.py` has no `thinking` field, `config.py`'s
`from_yaml()` never parses the key, and nothing has ever sent it to Ollama. The
declared value has been inert since the T-5 gate.

**Decision.** `ModelPlanner._ask()` passes `think=False` directly to
`chat()`. The registry is not consulted for it.

**Why.** Ollama leaves thinking ON for a Qwen3 model when no `think` key is
sent, so every planning call was generating a reasoning trace, charging it
against `num_predict`, and discarding it — nothing reads `message.thinking`.
Measured through `ModelPlanner.propose()` itself, model warm, `num_predict=1200`:

| | median `propose()` | thinking returned |
|---|---|---|
| no `think` key (before) | **15.4 s** | ~4 000 chars |
| `think=False` | **3.5 s** | 0 chars |

Same plans, same step counts, `done_reason="stop"` on every call, content never
empty. The full-suite live run fell from 64.9 s to 26.0 s. `next_step()` makes
one such call per iteration, so the saving compounds across a task.

**Why not thread it through the registry.** That is the better design, and it is
deliberately not done here: it needs a `thinking` field on `ModelEntry`
(`contracts.py`) and parsing in `from_yaml()` (`config.py`). Both are shared
files under CONTRIBUTING §1 and have to be announced before they change. Bundling
a shared-contract edit into a one-line latency fix is how a shared file changes
without anyone noticing. Same reasoning as D-019's tool-registry half.

**Consequence to accept.** Until that lands, `config/models.yaml`'s
`thinking: false` remains decorative, and a second caller that wants thinking off
must pass `think=False` itself. Whoever wires the field through should delete
this hardcoding and the `P1 TODO` in `llm/ollama_client.py::chat` together.
