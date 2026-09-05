# CONTRIBUTING

Six people, sixteen hours, one repository. These rules exist to stop the two
failure modes that kill hackathon projects: merge conflicts in shared files, and
integration hell at Hour 12.

---

## 1. Ownership — one owner per directory

Nobody edits another person's directory without a message first.

| Owner | Owns |
|---|---|
| **P1** | `backend/app/contracts.py`, `config.py`, `router.py`, `service.py`, `main.py`, `orchestration/`, `llm/`, `tools/registry.py`, `agents/__init__.py`, `mocks/` |
| **P2** | `backend/app/agents/vision.py`, `backend/app/tools/ocr.py` |
| **P3** | `backend/app/agents/reasoning.py`, `tools/kb.py`, `security/injection.py`, `data/kb_corpus/` |
| **P4** | `backend/app/agents/coding.py`, `tools/sandbox.py`, `tools/fs.py`, `security/paths.py`, `security/cors.py`, `security/netwatch.py`, `scripts/netwatch_classifier.py`, `scripts/preflight.py`, `sandbox/`, `docker/` |
| **P5** | all of `frontend/` |
| **P6** | `tools/docgen.py`, `tools/sheets.py`, `security/audit.py`, `security/integrity.py`, `templates/`, `data/demo_assets/`, `scripts/verify_audit.py`, `DEMO_SCRIPT.md` |

### Shared files — P1 coordination required

Changing any of these means messaging the group **before** you commit:

- `backend/app/contracts.py` — five people import from it
- `backend/app/config.py` — thresholds, attempt budgets, the iteration cap
- `config/models.yaml` — **FROZEN** at the T-5 benchmark gate. Changing a model
  or a `context_limit` before T-3 requires an emergency rollback with a recorded
  reason
- `backend/app/tools/registry.py` — the seven-tool allowlist
- `frontend/src/types.ts` — mirrors `contracts.py`; run the sync check

---

## 2. Branches and commits

```
main                      always runnable in mock mode; tests green
p<N>/<short-topic>        e.g. p2/ocr-cascade, p4/sandbox-exec, p5/audit-viewer
```

- Branch from `main`, rebase before you open a PR.
- Small commits with a real subject line. `wip` tells the next person nothing.
- **Never commit:** model weights, `vendor/`, `.env`, `node_modules/`,
  `frontend/dist/`, `logs/`, `data/chroma/`, runtime uploads in
  `data/workspace/`. `.gitignore` covers these; do not `-f` past it.
- Small synthetic fixtures **are** committed — they are how a teammate reproduces
  a demo beat without the real assets.

---

## 3. The integration check — run before every push

```bash
python -m pytest backend/tests -q            # must be green
python scripts/check_contract_sync.py        # frontend/backend drift
cd frontend && npm run build                 # if you touched frontend/
```

Windows: `.\.venv\Scripts\python.exe` in place of `python`.

Before every gate and before the demo, additionally:

```bash
python scripts/verify_audit.py
python scripts/preflight.py
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/health   # 200, JSON
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/            # 200, index.html
```

That second pair catches the route-ordering bug: if `/api/health` returns HTML,
the `dist` mount was registered before the API router.

---

## 4. Rules that are not style preferences

1. **Model tags live only in `config/models.yaml`.** A tag in a Python file
   breaks requirement R5 and a test fails.
2. **Seven tools.** Adding an eighth breaks a test and makes the pitch wrong. If
   you need new capability, it is a new *operation* on an existing tool or an
   internal service — not a new registry entry.
3. **No host execution of generated code, ever.** If Docker is down,
   `run_python` returns `SANDBOX_UNAVAILABLE`. Never add a subprocess fallback.
4. **An unimplemented real component fails loudly.** It never returns
   plausible-looking empty output that a demo could mistake for success.
5. **Mock fixtures never activate in real mode.** `build_planner` raises, and
   `POST /api/tasks` with a `scenario` returns 400.
6. **No new infrastructure.** No LangChain, LlamaIndex, Redis, Celery, Postgres,
   cloud API or separate agent framework. If you think you need one, that is a
   group conversation.
7. **Nothing downloads at startup or during a task.** No model pulls, no wheel
   installs, no `pip install` inside the sandbox.
8. **The frontend renders model output as plain text.** No
   `dangerouslySetInnerHTML`, no remote fonts, no CDN, no analytics.
9. **Heavy imports are lazy.** `chromadb`, `torch`, `pymupdf`, `pytesseract` and
   `docx` are imported inside the function that needs them, so a teammate
   without them installed can still run the app and the tests.
10. **Every unfinished seam names an owner and an acceptance criterion.**
    `# TODO: implement` is not acceptable; `# P3 TODO (acceptance: …)` is.

---

## 5. Honesty rules for anything user-visible

These are not politeness. They are what stops the project losing credibility in
the one moment that matters.

- Never report a skipped check as a pass. `ReadinessCheck.skipped` exists for
  this; the UI renders it differently from a tick.
- Never render an unchecked model digest as verified.
- Never collapse `trusted_lan` into `external`, and never add
  `blocked_external_attempts` into `external_active`.
- Never describe a sampled connection count of zero as proof no traffic ever
  occurred.
- Never call the audit chain tamper-proof. It is tamper-evident within stated
  assumptions.
- Never describe the regex list or XML tags as a complete prompt-injection
  defence.
- Never claim Docker isolation protects the host backend.
- Never claim deterministic fixtures demonstrate model reasoning.

If you catch yourself needing a qualifier to make a claim true, put the
qualifier on the screen, not just in the README.

---

## 6. When something breaks

1. Ten-minute rule: stuck for ten minutes, say so in the group. Blockers on a
   whiteboard get solved; blockers in one person's head do not.
2. Run `python scripts/preflight.py` first. It catches most environment problems
   before you debug the wrong layer.
3. If a contract looks wrong, message P1. Do not work around it locally — an
   assumption that diverges quietly costs an integration hour later.
