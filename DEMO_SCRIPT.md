# SETU Hackathon Demo Script (P6)

This runbook accurately reflects the current state of the repository. Every step aligns with implemented, functional components.

## 1. PRE-DEMO CHECKLIST
**Environment Assumptions:** 
- Windows host with Python 3.11+.
- `pip` installed and configured.

**Required Services:**
- Local Ollama instance running.
- (P5 Owned) React frontend running.
- (P4 Owned) Docker running for `setu-sandbox:py311` execution.

**Required Models & Dependencies:**
- Ollama models (manifests populated in local filesystem).
- Python dependencies (including `python-docx`, `openpyxl`, `python-pptx`, `pytest`).

**Required Assets:**
- `data/demo_assets/scanned_inspection_report.pdf`
- `data/demo_assets/handwritten_note.png`
- `data/demo_assets/p_and_id_crop.png`
- `data/demo_assets/sensor_readings.xlsx`
- `data/demo_assets/injected.pdf`
- `templates/approval_note.docx`
- `templates/calc.xlsx`
- `templates/review.pptx`

**Startup Commands:**
```bash
# Backend startup
uvicorn backend.app.main:app

# Frontend startup (P5-owned)
VERIFY AT INTEGRATION (e.g. npm run dev)
```

## 2. FLAGSHIP DEMO
This flow processes a noisy inspection report and produces an approval note.
1. **Upload:** User uploads `scanned_inspection_report.pdf` and `handwritten_note.png`.
2. **Router:** Intercepts prompt and routes to Vision (because of PDF/image payloads).
3. **Vision (Mocked/Scaffolded):** Extracts handwriting and anomalies.
4. **Orchestrator:** Formulates a plan based on Vision extraction.
5. **KB Grounding:** Cross-references the extracted anomalies with local standards.
6. **Reasoning:** Concludes the pipeline.
7. **Approval Note:** Triggers `docgen.py` via `_docx()` handler using `templates/approval_note.docx`.
8. **Delivery:** The generated DOCX is saved in the workspace and presented to the user.

## 3. SPREADSHEET DEMO
This explicitly demonstrates data privacy and local computation.
1. **Upload:** User provides `sensor_readings.xlsx`.
2. **`sheet_op("describe")`:** Runs first to map out available sheets and column schemas without reading full data. *Explanation: Describe happens first so the orchestrator understands the workbook structure without stuffing thousands of rows into the LLM context limit.*
3. **`sheet_op("read")`:** Pulls targeted slices of data based on the described schema.
4. **`sheet_op("compute")`:** Writes and executes a deterministic Python sandbox script to calculate statistics/anomalies (e.g., standard deviation, out-of-spec readings).
5. **`sheet_op("write")`:** Generates a new workbook using `templates/calc.xlsx`, conditionally formatting out-of-spec readings with strict hex color codes (e.g. `FF0000` for `REJECT`).
6. **Delivery:** The generated workbook is stored securely in the workspace.

## 4. AUDIT DEMO
SETU employs a tamper-evident audit chain.
- **Location:** The audit log is located outside the workspace at `logs/audit.jsonl`.
- **Verification:** Run `python scripts/verify_audit.py --path logs/audit.jsonl`.
- **Expected VALID Result:** `AuditVerification(ok=True, entries_checked=N, ...)`
- **Demonstrating Tampering:** Open `logs/audit.jsonl` in a text editor. Modify a single character in the `"action"` or `"result"` of an entry. Save.
- **Expected INVALID Result:** Run the verification script again. It will output `AuditVerification(ok=False, reason="entry_hash mismatch at line X: this line was modified")`.
- **Judge Explanation:** "A malicious actor with filesystem access can change a log, but because each step hashes its payload (`entry_hash`) and the previous entry (`prev_hash`), the cryptographic chain breaks exactly at the site of the tampering. Selective editing is mathematically impossible."

## 5. MODEL INTEGRITY DEMO
Proving that the underlying AI hasn't been swapped.
- **Source of Truth:** `backend/app/security/integrity.py` hashes the actual local model manifests found on disk (`~/.ollama/models/manifests/registry.ollama.ai/library/`).
- **Verification Logic:** It compares the on-disk SHA-256 manifest hashes directly against `config/model_allowlist.json`. NO network calls are made.
- **Distinctions:**
  - `VERIFIED`: Local hash matches the allowlist.
  - `MISMATCH`: Local hash differs (model has been tampered with or updated maliciously).
  - `UNAVAILABLE`: Manifest file doesn't exist on disk.
- **Judge Display:** The UI calls the `/api/models` endpoint which executes this check and surfaces the integrity status natively to the user.

## 6. PPTX DEMO
Demonstrating executive presentation generation.
- **Generation:** Triggered by `docgen.py` via the `_pptx()` handler.
- **Data Passed:** Structured payload with `{ "PRESENTATION_TITLE": "...", "EXEC_SUMMARY": "..." }`.
- **Validation:** Uses `python-pptx` to natively replace text inside paragraph runs of `templates/review.pptx`, strictly preserving bounding boxes, corporate typography, and slide layouts without corrupting the master template. Output is saved to the workspace.

## 7. SECURITY / SOVEREIGNTY SUPPORT
These components provide physical evidence of the system's sovereignty. *(Note: Do not implement here, refer to P4/P5.)*
- **Network Panel:** P5 UI overlay showing zero outbound WAN traffic. (VERIFY AT INTEGRATION)
- **Ollama Loopback:** `127.0.0.1` binding proofs for model inference.
- **Firewall:** Host-level block rules.
- **Sandbox Proof:** Docker isolated network demonstration for `sheet_op("compute")`.

## 8. FAILURE / FALLBACK PLAN
- **PPTX unavailable:** Fallback to DOCX. The prompt allows generating text summaries.
- **Docker/sandbox unavailable:** Explicitly skip `sheet_op("compute")` and rely on `sheet_op("read")` combined with Reasoning.
- **Ollama/model unavailable:** Run in `mock_mode=True` via `Settings`. (Pre-baked deterministic responses).
- **LAN demo unavailable:** Fallback to local host-only demo.
- **Generated artifact failure:** Open pre-generated examples in `data/demo_assets/`.
- **Live demo crash:** Restart the API server `uvicorn backend.app.main:app` (Audit logs will persist across restarts).

## 9. JUDGE Q&A

**"How would an internal auditor verify what this thing did?"**
*Answer:* Every action, prompt, and tool execution is logged into an append-only JSONL file (`logs/audit.jsonl`). Each entry contains a cryptographic `entry_hash` and a `prev_hash` linking it to the prior step. The auditor runs `scripts/verify_audit.py` to validate the chain. If a rogue administrator tries to selectively delete or edit an entry to cover their tracks, the cryptographic chain breaks and highlights exactly where the tampering occurred.

**"Why does the spreadsheet 'describe' happen first?"**
*Answer:* LLMs cannot ingest 50,000 rows of an Excel file without crashing or losing context. `sheet_op("describe")` allows the Orchestrator to cheaply map the schema (sheets, headers, types). The agent then writes deterministic Python code to process the data via `sheet_op("compute")` in a secure sandbox, safely handling unlimited scale.

**"How are generated documents kept separate from templates?"**
*Answer:* The `docgen` and `sheets` tools operate strictly read-only on the `templates/` directory. All generated artifacts are strictly confined to the `data/workspace/` jail. No system tool has permissions to write back to the template folder.

**"How is model integrity verified without internet?"**
*Answer:* We rely on the local filesystem. `integrity.py` hashes the actual Ollama model manifest files stored on disk and compares them to our predefined `config/model_allowlist.json`. We verify the local state byte-for-byte without making a single outbound network request.

## 10. 6-MINUTE TIMELINE
| Time | Phase | Focus |
|---|---|---|
| 0:00–0:30 | Framing | The sovereign AI premise. Zero external network. |
| 0:30–2:30 | Flagship | File upload, Vision extraction, Reasoning, DOCX output. |
| 2:30–3:30 | Spreadsheet | `describe` -> `compute` -> `write` conditional formatting. |
| 3:30–4:15 | Audit | `verify_audit.py` demonstration with a tampered line. |
| 4:15–4:45 | Integrity | Show model manifest verification vs allowlist. |
| 4:45–5:30 | Sovereignty | Network traffic panel / firewall proofs (P4/P5). |
| 5:30–6:00 | Closing | PPTX generation & Final Pitch. |

## 11. PRE-FREEZE CHECKLIST
```bash
# Dependency Validation
cat backend/requirements.in
python -c "import docx; import openpyxl; import pptx"

# Focused P6 Tests
python -m pytest backend/tests/test_docgen.py backend/tests/test_docgen_pptx.py backend/tests/test_sheets_compute.py backend/tests/test_sheets_write.py backend/tests/test_integrity.py -v

# Full Suite
python -m pytest backend/tests/ -v

# Preflight
VERIFY AT INTEGRATION (python scripts/preflight.py)

# Frontend Build (P5-Owned)
VERIFY AT INTEGRATION (npm run build)

# Artifact Validation
ls data/workspace/

# Git Review
git status --short
git diff
```

## 12. CUT LIST
**MUST DEMO:**
- File Upload & Flagship DOCX generation.
- Spreadsheet `describe` -> `compute` -> `write`.
- Audit chain tampering detection.

**NICE TO HAVE:**
- Model integrity allowlist verification.
- PPTX automated slide generation.

**CUT FIRST IF TIME IS LOW:**
- Advanced adversarial injection demonstration (`injected.pdf`).
- Sandbox fallback workflows.
