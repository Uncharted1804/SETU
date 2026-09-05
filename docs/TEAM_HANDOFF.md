# TEAM HANDOFF

One section per owner. Each states: what you own, what already works, what you
build next in order, the exact contracts, the mock you replace, how to run your
component alone, your acceptance criteria, your integration partner, and the
shared files that need P1 coordination.

**Before you start:** read [`STATUS.md`](STATUS.md). The blueprint says a
security spine and 26 tests already existed; they did not. What exists now is
listed there honestly.

**Universal rules**

- `backend/app/contracts.py` is P1's. Announce before changing it.
- No model tag goes anywhere except `config/models.yaml`.
- Nothing downloads a model, a wheel or an npm package at startup or during a task.
- An unimplemented real component fails loudly. It never returns plausible-looking
  empty output.
- Run `python -m pytest backend/tests -q` before you push. It must stay green.

---

## P1 — Orchestrator, Router, Tech Lead

**You own:** `contracts.py`, `config.py`, `router.py`, `service.py`, `main.py`,
`orchestration/*`, `llm/ollama_client.py`, `tools/registry.py`, `agents/__init__.py`,
`mocks/*`, `scripts/check_contract_sync.py`, and every integration gate.

**Already works.** All of it, in mock mode: contracts with validation, the
registry reading the frozen YAML, five router rules, the generic executor with
approvals/retries/escalation/caps, the dispatcher, the event bus with replay,
every API route, the app factory with correct route ordering. 196 tests pass.
The Ollama transport is written but has **never been called against a running
server**.

**Build next, in order.**

1. **Exercise `llm/ollama_client.py` against real Ollama.** Acceptance:
   `list_models()` returns the seven installed tags; `chat()` returns a response
   from `qwen3:8b`; a non-loopback `OLLAMA_HOST` still refuses to start.
2. **`ModelPlanner`** in `orchestration/planner.py` — the three methods, prompting
   the reasoning agent with `registry.schemas()`. Acceptance: with
   `SETU_MOCK_MODE=0`, a text-only task produces a 1–5 step validated plan, and
   the second `next_step` call reflects the first step's observation. Remember
   D-016: return the object from `plan.steps`, not a copy.
3. **Token streaming.** Wire `chat_stream()` into the reasoning path and emit
   `token` events. Acceptance: text appears in the UI within 2 s of `step_start`.
4. **Call the gates** and make the Hour-10 cut decisions.

**Contracts.** You define them; see [`CONTRACTS.md`](CONTRACTS.md).

**Mock you replace:** `MockPlanner` → `ModelPlanner`.

**Run it alone:**
```bash
python -m pytest backend/tests -q
python scripts/check_contract_sync.py
./scripts/dev.sh                      # or .\scripts\dev.ps1
```

**Acceptance:** the spine is up, everyone else can plug in, and every contract
change was announced before it landed.

**Integration partner:** everyone. Pair at the seams: P5 on the SSE contract,
P6 on the tool registry signature, P2 on the vision relay, P4 on the retry loop.

**Shared files:** you are the coordination point. Nobody else edits
`contracts.py`, `config.py`, `orchestration/*` or `tools/registry.py` without
messaging you first.

---

## P2 — Vision / OCR Agent

**You own:** `backend/app/agents/vision.py`, `backend/app/tools/ocr.py`, all
image preprocessing.

**Already works.**
- The orchestrator calls your agent through the dispatcher with attempts,
  feedback and escalation already handled — you only implement `run()`.
- `ocr.py::cascade_plan()` is real, tested logic for tier selection.
- `tesseract_available()` is a real readiness probe.
- `MockAgent("vision")` returns five findings across three pages with mixed
  extraction tiers, so the whole flagship runs without you.

**Build next, in order.**

1. **`tier1_text_layer()`** — PyMuPDF. *Acceptance:* a digital PDF yields exact
   text, `extraction_tier="text_layer"`, per-block bboxes in PDF points.
2. **`rasterize()`** — 300 dpi PNG per page, written **inside the workspace via
   `ctx.resolve`**, never a temp dir outside the jail.
3. **`tier2_tesseract()`** — *Acceptance:* the demo scan yields ≥ 5 findings with
   word-level confidences, twice in a row. Missing binary raises a clear
   `ToolError`; it never silently falls through to the VLM.
4. **`VisionAgent.run()`** — assemble the cascade, call
   `client.chat_vision(..., format_schema=VisionOutput.model_json_schema())`.
   *Acceptance:* scanned inspection report → `VisionOutput` with
   `overall_confidence ≥ 0.70`.
5. **Retry path** — `preprocess()` (CLAHE + deskew) and `crop_to_bbox()`, driven
   by `inv.feedback` and the lowest-confidence finding. *Acceptance:* attempt 2
   measurably raises confidence on the deliberately blurry demo region, and
   re-asks about ONE region, not the whole page.

**Contracts.**
- **In:** `AgentInvocation{agent="vision", model, model_id, inputs, attempt, feedback}`.
  `inputs.args` carries the step args; file paths are workspace-relative.
- **Out:** `AgentResult{payload=VisionOutput.model_dump(), attempts=[Attempt],
  final_confidence}`. `final_confidence` is what the policy compares to 0.70.
- **Findings:** pages 1-indexed, `bbox = [x0,y0,x1,y1]` PDF points, top-left
  origin, `extraction_tier ∈ {text_layer, tesseract, vlm}`.

**Mock you replace:** `MockAgent("vision")` in `app/mocks/adapters.py`.

**Run it alone:**
```bash
python -c "import sys; sys.path.insert(0,'backend'); from app.tools.ocr import cascade_plan; print(cascade_plan(False, 0.6))"
SETU_MOCK_MODE=0 python -m pytest backend/tests -q -k vision
```

**Acceptance at Gate 2:** the scanned report reliably yields ≥ 5 clean findings,
twice in a row. Nothing else in the build matters as much.

**Integration partner:** P3 (findings → reasoning prompt is the flagship join),
P1 (the relay). Shared seam: `VisionOutput` in `contracts.py`.

**Needs P1 coordination:** any change to `Finding`, `VisionOutput` or
`ExtractionTier`.

---

## P3 — Reasoning Agent & Knowledge Base

**You own:** `backend/app/agents/reasoning.py`, `backend/app/tools/kb.py`,
`backend/app/security/injection.py`, `data/kb_corpus/`.

**Already works.**
- `injection.py` is complete and tested: `scan()`, `wrap_untrusted()`,
  `quarantine()`, `screen_chunks()`, `build_context_block()`, plus
  `SYSTEM_DATA_RULE`.
- `kb.py::chunk_text()` is real, tested, dependency-free (800/150, recursive).
- `KnowledgeBase.search()` is implemented against embedded Chroma with CPU
  embeddings — it just has nothing indexed.
- `mock_kb_search` returns fixture SOP chunks so the flagship runs without you.
- The `injection` scenario already renders the quarantine banner in the UI.

**Build next, in order.**

1. **The corpus.** 15–25 realistic documents in `data/kb_corpus/`: an inspection
   SOP, hydrotest acceptance criteria, a safety circular, 2–3 vendor letters, a
   tolerance/spec table (the sensor demo needs this one), and a few unrelated
   documents so retrieval must discriminate. **This is pre-hackathon work.**
2. **`KnowledgeBase.ingest()`** — chunk, `injection.scan()` **before** indexing,
   quarantine flagged chunks and surface them. *Acceptance:*
   `kb_search("hydrotest acceptance criteria")` returns ≥ 3 chunks from the
   expected SOP under the calibrated cutoff, and the injected demo PDF produces
   exactly one quarantined chunk.
3. **Calibrate retrieval.** `config/models.yaml` leaves `retrieval.top_k` and
   `distance_cutoff` null on purpose. Set them from a labelled query set and
   record `calibrated_on`. Do not ship a universal cosine cutoff.
4. **`ReasoningAgent.run()`** — findings + wrapped chunks + role prompt.
   *Acceptance:* an approval note with ≥ 3 citations. **Every chunk goes through
   `wrap_untrusted`; `SYSTEM_DATA_RULE` goes in the system message.** Write a
   test asserting no chunk text reaches the instruction region unwrapped.
5. **The Verifier** — rapidfuzz-match each drafted sentence against retrieved
   spans; unsupported ones go in `unsupported_claims`. *Acceptance:* the demo
   produces exactly one yellow unsupported claim.
6. **Retry path** — use `inv.feedback` to widen or change retrieval, not to
   re-ask verbatim.

**Contracts.**
- **In:** `AgentInvocation`; `inputs.prior` carries the vision observation.
- **Out:** `AgentResult{payload=ReasoningOutput.model_dump(), ...}`.
  Threshold 0.65, 3 attempts.
- **`kb_search` returns** `{query, chunks: [Chunk], quarantined: [Chunk], count}`.
  `Chunk.distance` is a cosine DISTANCE — lower is closer, not a similarity.

**Mocks you replace:** `MockAgent("reasoning")` and `mock_kb_search`.

**Run it alone:**
```bash
python -c "import sys; sys.path.insert(0,'backend'); from app.tools.kb import chunk_text; print(len(chunk_text(open('data/kb_corpus/x.md').read())))"
python -m pytest backend/tests/test_security_config.py -q -k injection
```

**Acceptance:** grounded drafting with citations and yellow flags, and a red
quarantine banner on the injected PDF.

**Integration partner:** P2 (findings in), P6 (reasoning output → docgen).

**Needs P1 coordination:** `Chunk`, `ChunkMetadata`, `Citation`, `ReasoningOutput`.

**Say it accurately:** the regex list is a tripwire, not a complete defence. The
real answer to injection is that there is no egress tool.

---

## P4 — Coding Agent, Sandbox, Security & Infrastructure

**You own:** `backend/app/agents/coding.py`, `tools/sandbox.py`, `tools/fs.py`,
`security/paths.py`, `security/cors.py`, `security/netwatch.py`,
`scripts/netwatch_classifier.py`, `scripts/preflight.py`, `scripts/launch_lan.sh`,
`sandbox/`, security layers 1–3.

**Already works — but read this first.** The blueprint marks `cors.py`,
`netwatch.py` and `netwatch_classifier.py` as DONE and frozen. **They did not
exist.** P1 wrote them to the specified behaviour with 40+ tests. Review them as
new code, not as reviewed code.

- `security/paths.py::jail()` — traversal, drive-qualified and resolved-symlink
  escapes all blocked and tested.
- `fs.py` — `read_file`, `write_file`, `list_dir`, real in both modes.
- `sandbox.py::build_command()` — the nine controls, tested.
- `netwatch_classifier.py` — four buckets, `ip.is_private` deliberately unused,
  listening sockets excluded; includes the three assertions the blueprint states
  verbatim.
- `cors.py` — off by default, fails closed, never a wildcard.
- `run_in_sandbox()` is written but **has never been run against Docker**.

**Build next, in order.**

1. **T-3, not negotiable: the Windows firewall check** on the real laptop.
   *Acceptance:* three checks pass on Windows, not advisory-skipped. Currently
   marked UNVERIFIED in STATUS.md.
2. **T-3: the cross-device proof.** From a teammate's laptop:
   `curl -m 3 http://<host>:11434/api/tags` must refuse or time out;
   `curl -m 3 http://<host>:8000/api/health` must return 200. **Screenshot it.**
   The same-host check is only a precondition, not the proof.
3. **Verify the sandbox actually executes.** `docker load -i
   vendor/setu-sandbox-py311.tar`, then `run_python("print(2+2)")` → stdout `4`,
   exit 0, and the printed command matches `build_command()` exactly.
4. **`CodingAgent.run()`** — generate code, run it in the sandbox, return
   `CodingOutput`. *Acceptance:* the demo script fails on attempt 1, the
   traceback is fed back, attempt 2 passes, and the UI shows
   `attempt 2/4 · feeding failure back into the retry`.
5. **Add the route-order assertion to `preflight.py`** (blueprint 0.5): a live
   `/api/health` returns JSON, not HTML. There is already a test for it
   (`test_api_health_survives_the_frontend_mount`); preflight should check the
   running process too.
6. **Review P6's read-only workbook mount** for `sheet_op("compute")`.

**Contracts.**
- **In:** `AgentInvocation`; `inputs.prior` carries earlier observations.
- **Out:** `AgentResult{payload=CodingOutput.model_dump(), ...}`.
  **`CodingOutput.confidence` must be exactly 1.0 iff `exit_code == 0`** — the
  contract enforces it. Threshold 1.00, 4 attempts.
- **`run_python`** takes `{code, timeout≤60, input_paths}`; `input_paths` are
  mounted READ-ONLY at `/inputs/`.

**Mocks you replace:** `MockAgent("coding")` and `mock_run_python`.

**Run it alone:**
```bash
python -m pytest backend/tests/test_jail.py backend/tests/test_netwatch_classifier.py -q
python -m pytest backend/tests/test_security_config.py -q
python scripts/preflight.py
python scripts/offline_check.py
```

**Acceptance:** `_jail("../../etc/passwd")` raises on stage in four seconds; a
script fails and self-corrects; the sandbox command renders on screen.

**Integration partner:** P1 (retry feedback loop), P6 (compute mount).

**Needs P1 coordination:** `CodingOutput`, `RunPythonArgs`, anything in
`tools/registry.py`.

**Never add a host-execution fallback to `sandbox.py`.** If Docker is
unavailable, return `SANDBOX_UNAVAILABLE`. A test asserts the module launches
nothing but the docker CLI.

**Say it accurately:** the nine flags isolate generated code, not the SETU
backend. Host isolation is a deployment requirement — see ARCHITECTURE.md.

---

## P5 — Frontend & Observability

**You own:** all of `frontend/`, and the build discipline that goes with it.

**Already works.** A functional dark workbench, built and verified in a browser:
prompt + upload, router banner, plan checklist with approve/reject, live SSE
stream, retry and escalation display, artifact download, network panel, model
registry, audit viewer with one-click verify. `npm run build` passes.

**Build next, in order.**

1. **Density and polish.** The layout is functional, not finished. Match the
   density of a real tool. Budget real time on the router banner and the network
   panel — they carry the two core claims.
2. **Token streaming display.** The `token` event is already handled by
   `useTaskStream`; once P1 emits them, make the draft render as it streams.
3. **Findings and citations rendering.** `VisionOutput.findings` (with
   extraction tier badges — the mixed-tier story is a strong beat) and
   `ReasoningOutput.citations`, with `unsupported_claims` in yellow.
4. **Audit chain as linked blocks**, tamper → red.
5. **Uptime and negative-control display** on the network panel.

**Contracts.** `frontend/src/types.ts` mirrors `contracts.py`.
**Run `python scripts/check_contract_sync.py` before every gate** — it caught a
real missing field on its first run.

**Traps already handled for you, do not undo them.**
- The server sets `event: <type>` on every SSE message, so a browser dispatches
  to `addEventListener(type, …)`, **not** `onmessage`. `useTaskStream` registers
  one listener per type. Remove them and the stream silently delivers nothing.
- Four network counters are never collapsed into fewer.
  `blocked_external_attempts` renders on its own row, never added to `external`.
- An unchecked model digest renders "digest not verified", never a tick.
- Model output is rendered as plain text. **No `dangerouslySetInnerHTML`,
  anywhere.**
- No remote fonts, no CDN, no analytics. An air-gapped machine must render
  identically.

**Run it alone:**
```bash
cd frontend && npm run dev        # Vite :5173, proxying /api to :8000
./scripts/dev.sh --ui             # backend with gated dev CORS
cd frontend && npm run typecheck
```

**Acceptance:** every surface renders from real backend events; `npm run build`
is on the demo checklist in bold. **A UI change that was not rebuilt does not
exist in the demo.**

**Integration partner:** P1 (SSE contract), P6 (audit + network panels).

**Needs P1 coordination:** any new field you need on an API response.

---

## P6 — Deliverables, Audit, Integrity & Demo

**You own:** `tools/docgen.py`, `tools/sheets.py`, `security/audit.py`,
`security/integrity.py`, `templates/`, `data/demo_assets/`,
`scripts/verify_audit.py`, `DEMO_SCRIPT.md`, the pitch deck.

**Already works.**
- `security/audit.py` — canonical hash chain (`sort_keys`, fixed separators,
  `entry_hash` excluded from its own hash), serialised appends, concurrent-safe,
  verification. 13 tests including tamper and deletion detection.
- `scripts/verify_audit.py` — CLI with `--json` and `--show N`.
- `docgen("docx")` and `docgen("xlsx")` produce genuine openable files; the mock
  flagship yields a real 37 kB approval note.
- `sheet_op` `describe`, `read` and `write` are real openpyxl implementations;
  `describe` correctly reports a mixed-type column.

**Build next, in order.**

1. **Templates.** `templates/approval_note.docx`, `calc.xlsx`, `review.pptx`
   with correct letterhead, headers and signature block. Then load them via
   `DocgenArgs.template`. *Acceptance:* `docgen("docx", MOCK_DATA)` produces a
   file you would actually sign.
2. **Demo assets** in `data/demo_assets/`: the scanned inspection report
   (print → photograph → PDF; slight skew is good), a handwritten note, a P&ID
   crop, `sensor_readings.xlsx` (two sheets, ~400 rows, merged header, one stray
   text value in a numeric column, three deliberate out-of-spec values), and the
   injected PDF (white 4 pt text on page 7). Currently only two synthetic PNGs
   exist.
3. **`sheet_op("compute")`** — translate `spec` into a script, run it via
   `sandbox.run_in_sandbox` with the workbook mounted read-only, capture named
   intermediates as JSON on stdout. *Acceptance:* a numeric result plus the
   script and intermediates; a write attempt inside the sandbox fails.
4. **`sheet_op("write")` formatting** — *Acceptance:* the three out-of-spec rows
   render red.
5. **`security/integrity.py::verify_installed()`** — read local Ollama manifests
   only, compare to `expected_manifest_digest` and `config/model_allowlist.json`.
   *Acceptance:* `/api/models` reports real true/false, and the panel shows one
   verified row. **Until then it must stay `null` = never checked.**
6. **`docgen("pptx")`** — cut-list item 3, lowest priority.
7. **`DEMO_SCRIPT.md`** and three timed rehearsals with a different driver each.

**Contracts.**
- **`docgen`** takes `{kind, data, template?, out_name?}` and returns
  `{kind, artifact_id, path, size_bytes, sha256}`. It is `requires_approval`:
  the human sees the actual body text before the file is written.
- **`sheet_op`** — see [`CONTRACTS.md`](CONTRACTS.md) §2. `write` never
  overwrites its input; the contract enforces it.
- **Audit** — call `AuditLog.append(...)`; never write the JSONL by hand, or the
  chain breaks.

**Mock you replace:** `mock_sheet_op`.

**Run it alone:**
```bash
python scripts/verify_audit.py --show 20
python -m pytest backend/tests/test_audit.py -q
python -c "import sys; sys.path.insert(0,'backend'); from app.tools.sheets import _describe; print('ok')"
```

**Acceptance:** tamper a line → verifier red; a sandbox-computed result lands in
a formatted workbook; the `.docx` and `.xlsx` both open correctly.

**Integration partner:** P4 (the compute mount), P3 (reasoning → docgen),
P5 (audit viewer).

**Needs P1 coordination:** `AuditEntry`, `DocgenArgs`, `SheetOpArgs`,
`ComputeResult`, `ArtifactRef`.

**Say it accurately:** the chain is tamper-EVIDENT within stated assumptions. A
selective edit is detectable; an operator-level attacker who rewrites the whole
file is not. Say that before someone else says it for you.

**You are the only person allowed to say "we're out of time, cut it." Use it.**
