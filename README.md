# SETU

**Sovereign on-premise agentic AI workbench.** Three open-weight models on the
organisation's own GPU, auto-selected per task, chained by an orchestrator that
plans, retries and escalates, grounded in the organisation's own documents,
producing real Word/Excel deliverables — with a capability surface narrow enough
that a total prompt-injection compromise produces a wrong paragraph, not a breach.

SIH 2026 · Problem statement 26117 · Mangalore Refinery and Petrochemicals Limited.

> **This repository is an integration scaffold, not a finished product.**
> The orchestration spine, contracts, API, security baseline and UI are real and
> tested. The agents, OCR cascade, knowledge base and sandbox execution are
> typed seams with deterministic mock adapters behind them, each assigned to an
> owner. [`docs/STATUS.md`](docs/STATUS.md) is the honest matrix of what is real,
> mocked, scaffolded and unverified. Read it before claiming anything to anyone.

---

## Quickstart — mock mode (no GPU, no Ollama, no Docker)

Mock mode runs the entire application with deterministic fixtures. You need
Python 3.12 and the dependencies in `backend/requirements-lock.txt`. You do
**not** need a GPU, Ollama, Docker, Tesseract, an embedding download or a
populated knowledge base.

**Windows PowerShell**

```powershell
cd C:\Users\shaur\Desktop\setu
.\.venv\Scripts\Activate.ps1
cd frontend; npm install; npm run build; cd ..
.\scripts\dev.ps1
```

**Linux / WSL / macOS**

```bash
cd ~/setu
source .venv/bin/activate
(cd frontend && npm install && npm run build)
./scripts/dev.sh
```

Then open <http://127.0.0.1:8000>. You should see a yellow **MOCK MODE** banner.
Type a task, approve the plan, watch the steps tick, download a real `.docx`.

These prompts reach each scenario:

| Prompt | What you see |
|---|---|
| `Draft an approval note from this inspection report.` | The flagship: vision → kb_search → reasoning → docgen, with a downloadable Word file |
| `Check these readings against spec` | `sheet_op(describe)` reports a mixed-type column, so the loop inserts a `kb_search` that was **not** in the approved plan — and asks you again before running it |
| `Here is a traceback, fix this code` | Attempt 1 fails, the traceback is fed back, attempt 2 passes |
| `The scan is degraded` | Three attempts below threshold → `needs_human_review`, no artifact |
| `This vendor letter looks odd` | A retrieved chunk is quarantined and surfaced, never used as context |
| Pick `rejection` in the dropdown, then **Reject** | Execution stops with nothing run and no file produced |

The dropdown next to **Run** selects a scenario explicitly.

## Real mode

Real mode needs the pre-staged environment: Ollama on loopback with the models
in `config/models.yaml` already pulled, Docker with `setu-sandbox:py311` already
built, and Tesseract installed. See [`docs/SETUP_KIT.md`](docs/SETUP_KIT.md) and
`SETUP_GUIDE.md` for that preparation. **Nothing is downloaded at startup or
during a task** — that is deliberate, and it is why setup is a separate step.

```powershell
.\scripts\dev.ps1 -Real
```

```bash
./scripts/dev.sh --real
```

Real mode fails loudly wherever a component is not yet implemented. That is
correct: an unimplemented real component must never quietly return
plausible-looking output.

**LAN mode** (a colleague on the same subnet uses your machine):

```bash
./scripts/launch_lan.sh 192.168.50.0/24
```

Use the subnet you *actually observe* — a hotspot hands out a different range
every session. An invalid subnet is a hard startup failure, never a silent
fallback to single-laptop mode.

## Frontend development

The demo runs against `frontend/dist`, served by FastAPI at the same origin as
`/api/*`. **A UI change that was not rebuilt does not exist.**

```powershell
.\scripts\dev.ps1 -Ui
```

```bash
./scripts/dev.sh --ui
```

Dev CORS requires **both** `SETU_DEV_MODE=1` and `SETU_DEV_ORIGINS`; with the
first and not the second it installs nothing and logs a warning. A wildcard
origin is never installed under any input. Before every gate and the demo:
`cd frontend && npm run build`, then hit `:8000` directly with dev mode off.

## Commands

| Command | What it does |
|---|---|
| `python -m pytest backend/tests -q` | The full suite — mock mode, no external services |
| `python scripts/check_contract_sync.py` | Fails if `frontend/src/types.ts` drifted from `contracts.py` |
| `python scripts/verify_audit.py` | Walks the audit hash chain; `--show 20` tails it |
| `python scripts/preflight.py` | P4's environment gate (Ollama, models, Docker, workspace, route order) |
| `python scripts/offline_check.py` | The three-part network proof, for rehearsal |
| `cd frontend && npm run build` | Produce `frontend/dist` — on every gate checklist |
| `cd frontend && npm run typecheck` | TypeScript check without emitting |

On Windows use `.\.venv\Scripts\python.exe` in place of `python` if the
virtualenv is not activated.

## Layout

```
backend/app/
  contracts.py          shared types - P1 only, changes announced
  config.py             settings, thresholds, model registry loader
  router.py             rule-based ENTRY routing (no model tags live here)
  service.py            dependency wiring; the 3 places mock and real diverge
  main.py               app factory - CORS, then /api/*, THEN the dist mount
  orchestration/        the loop: planner, dispatcher, executor, policy,
                        approvals, events, task state
  agents/               vision [P2] reasoning [P3] coding [P4] + registry
  tools/                the seven tools + the shared jail/sandbox services
  security/             paths, cors, netwatch, audit, injection, integrity
  mocks/                deterministic scenarios and adapters
frontend/               React 18 + TS + Vite 5 + Tailwind 3 [P5]
scripts/                dev launchers, preflight, audit verify, contract sync
config/models.yaml      FROZEN model registry - the only place model tags live
sandbox/Dockerfile      setu-sandbox:py311, built ahead of time
docs/                   ARCHITECTURE, CONTRACTS, TEAM_HANDOFF, DECISIONS, STATUS
```

## Documentation

| Document | Read it when |
|---|---|
| [`docs/STATUS.md`](docs/STATUS.md) | Before claiming anything works |
| [`docs/TEAM_HANDOFF.md`](docs/TEAM_HANDOFF.md) | You are P1–P6 and want your next task |
| [`docs/CONTRACTS.md`](docs/CONTRACTS.md) | You are implementing against an interface |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | You want to know how the pieces connect |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | The blueprint was ambiguous and you want to know how it was resolved |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Before your first commit |

## Known limitations

State these out loud rather than being caught on them.

- **Mock mode is fixtures.** A deterministic scenario proves the loop can select
  a next action from an observation. It proves nothing about model reasoning.
- **In-memory task store.** Restart the backend and in-flight tasks are gone.
  No Redis, no Celery, no database — deliberate for a single-operator workstation.
- **The audit chain is tamper-evident, not tamper-proof.** A selective edit
  breaks it; an operator-level attacker can rewrite the whole file.
- **Sandbox flags isolate generated code, not the SETU backend**, which runs on
  the host as a normal user process. Host-level isolation is a deployment
  requirement — see `docs/ARCHITECTURE.md`.
- **A sampled zero is not a proof of zero.** The network panel reports what one
  sample of this process's sockets showed, says so on screen, and reports a
  failure to sample rather than showing reassuring zeros.
- **Model integrity is not verified.** Digests render as "digest not verified"
  because nothing has computed them.
- **Windows firewall scoping and the cross-device proof have not been run** on
  this machine. They are P4 tasks, marked unverified in `docs/STATUS.md`.
- **Injection defence is regex tripwires plus architecture.** The regex list is
  not a complete defence and must not be described as one. The real answer is
  that there is no egress tool.
