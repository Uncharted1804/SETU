# P3 Knowledge Base — Oil Refinery Corpus (Chroma)

## What's in this folder

- **40 synthetic docs** (`01_*.md` – `40_*.md`): 35 real refinery documents +
  5 decoys, mapped to the problem statement's categories:
  - Approval notes → `25_approval_note_example_past.md`
  - Financials / vendor negotiation → `26_vendor_negotiation_budget_letter.md`
  - Unreleased designs / confidential strategy → `27_confidential_strategy_memo_capacity_expansion.md`
  - Internal correspondence → memos (`23`, `24`, `35`), vendor letters (`11`-`14`)
  - Manuals & SOPs → inspection, hydrotest, CUI, hot work, confined space,
    NDT, welding, relief valve, tank, piping, heat exchanger procedures
  - P&ID reference → `10_pid_symbol_reference.md` (tag/numbering convention
    only — no actual drawing is reproduced)
- `ingest_chroma.py` — chunks each doc, embeds with a local CPU model
  (`all-MiniLM-L6-v2`), writes to a **local, on-disk Chroma collection**.
- `kb_search.py` — the `kb_search(query, k=5)` function `reasoning.py`
  should import.
- `test_queries.md` — 14 validation queries + which decoys must NOT surface.

All equipment/document IDs (V-1042, C-101, E-205, RV-118, etc.) are reused
consistently across documents so cross-referencing (an audit history citing
a vendor letter citing a memo) looks and behaves like a real plant's
document set.

## One-time setup

```bash
pip install chromadb sentence-transformers
```

No external service or Docker container is required — Chroma persists to a
local folder (`chroma_db/` next to this README) by default.

## Ingest

```bash
python ingest_chroma.py
```

First run downloads `all-MiniLM-L6-v2` (~90MB, one-time). After that,
everything is local — no network calls at ingest or query time.

## Test retrieval (T-3 validation)

```bash
python kb_search.py "hydrotest acceptance criteria"
```

Run all 14 queries from `test_queries.md` and confirm the expected doc
appears in the top 3, and no decoy (36-40) does.

## Before the demo — critical sync step

`04_spec_tolerance_table.md` contains placeholder values. **Get the real
numbers from P6's `sensor_readings.xlsx` → `Spec_Limits` sheet and copy them
in exactly**, then re-run `ingest_chroma.py`. If these two disagree, the
reasoning agent's out-of-spec flag will contradict the spreadsheet on stage.

## Injection defence note

Do NOT add a fake "injected" document to this corpus. The real injected PDF
(hidden text, page 7) is P6's asset under `data/demo_assets/`. Your
`security/injection.py` should treat ALL content returned by `kb_search()`
the same way: wrap it in a structural tag (e.g. `<retrieved_context>`)
before it ever reaches a prompt, and never let its contents be interpreted
as instructions. Documents 26 and 27 are deliberately marked CONFIDENTIAL
in their own text — this is a good live test that your grounding logic can
cite a confidential internal doc for context without ever "obeying" any
instruction-like text a document might contain.
