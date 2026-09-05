"""
SETU benchmark_models.py -- the T-5 gate (blueprint section 6.5)

Measures, on the actual presentation machine, for every registered model:
  - cold-load time
  - time to first token
  - tokens per second
  - peak dedicated GPU memory
  - whether `ollama ps` reports full GPU placement or a CPU/GPU split
  - structured-output success on 5 representative tasks
  - tool-call success on 5 representative tasks

Then applies the keep/demote rule and writes docs/BENCHMARKS.md.

Stdlib only, so it runs before the venv exists.

Usage:
    python scripts/benchmark_models.py
    python scripts/benchmark_models.py --out docs/BENCHMARKS.md --runs 3
    python scripts/benchmark_models.py --only qwen3:8b
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import re
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

OLLAMA = "http://127.0.0.1:11434"
REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# What we test. Slot -> (primary, fallback, context, timing budget in seconds)
# ---------------------------------------------------------------------------
SLOTS = [
    ("reasoning", "qwen3:8b", "qwen3:4b-instruct", 8192, 25.0),
    ("coding", "qwen2.5-coder:7b", "qwen2.5-coder:3b", 8192, 30.0),
    ("vision", "qwen3-vl:4b", "qwen3-vl:2b", 4096, 20.0),
]

# Five representative structured-output tasks, close to the real demo shape.
STRUCTURED_TASKS = [
    (
        "extract_inspection_fields",
        "Extract fields from this inspection note and reply with ONLY a JSON object "
        "with keys equipment_id, inspection_date, defect_found, severity. "
        "Note: 'Pump P-104 inspected 2024-03-11. Minor seal weep observed. Severity: low.'",
        {"equipment_id", "inspection_date", "defect_found", "severity"},
    ),
    (
        "route_decision",
        "Reply with ONLY a JSON object with keys task_type and reason. "
        "Task: 'compute the mean vibration from this spreadsheet'.",
        {"task_type", "reason"},
    ),
    (
        "evidence_summary",
        "Reply with ONLY a JSON object with keys finding, citation_page, confidence_basis. "
        "Source page 4 states the hydrostatic test pressure is 1.5x design pressure.",
        {"finding", "citation_page", "confidence_basis"},
    ),
    (
        "plan_step",
        "Reply with ONLY a JSON object with keys next_tool and arguments. "
        "Available tools: sheet_describe, sheet_read, sheet_compute. "
        "You have not yet inspected the workbook.",
        {"next_tool", "arguments"},
    ),
    (
        "approval_note",
        "Reply with ONLY a JSON object with keys title, recommendation, requires_human_review. "
        "Context: a low-severity seal weep on a non-safety-critical pump.",
        {"title", "recommendation", "requires_human_review"},
    ),
]

# Vision-only structured-output tasks. Unlike STRUCTURED_TASKS (shared by all
# three slots, text-only), these send a real image through `images` so the
# vision slot is actually tested on its real job: extracting fields from a
# scanned-looking page, not parsing prose. Images are synthetic fixtures
# (data/demo_assets/vision_bench/), not the final curated demo scan.
VISION_TASKS = [
    (
        "extract_fields_from_scan_1",
        "Extract fields from this inspection report image and reply with ONLY "
        "a JSON object with keys equipment_id, inspection_date, defect_found, severity.",
        {"equipment_id", "inspection_date", "defect_found", "severity"},
        REPO_ROOT / "data" / "demo_assets" / "vision_bench" / "sample_1.png",
    ),
    (
        "extract_fields_from_scan_2",
        "Extract fields from this inspection report image and reply with ONLY "
        "a JSON object with keys equipment_id, inspection_date, defect_found, severity.",
        {"equipment_id", "inspection_date", "defect_found", "severity"},
        REPO_ROOT / "data" / "demo_assets" / "vision_bench" / "sample_2.png",
    ),
]

TOOL_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "sheet_describe",
            "description": "Describe sheet names, dimensions, headers and inferred types",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_search",
            "description": "Search the local knowledge base of manuals and SOPs",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}, "top_k": {"type": "integer"}},
                "required": ["query"],
            },
        },
    },
]

TOOL_PROMPTS = [
    "Describe the structure of the workbook at data/input/readings.xlsx before reading it.",
    "Find the SOP section covering hydrostatic test pressure limits.",
    "I need the sheet names and headers of data/input/inspection.xlsx.",
    "Look up the vibration acceptance criteria in the local manuals.",
    "Inspect data/input/q3.xlsx structure first, then we will compute.",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def post(path: str, payload: dict, timeout: int = 600):
    req = urllib.request.Request(
        f"{OLLAMA}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def post_stream(path: str, payload: dict, timeout: int = 600):
    """Yield (elapsed_seconds, parsed_chunk) for a streaming endpoint."""
    req = urllib.request.Request(
        f"{OLLAMA}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for line in resp:
            line = line.strip()
            if not line:
                continue
            try:
                yield time.perf_counter() - start, json.loads(line.decode())
            except json.JSONDecodeError:
                continue


def gpu_used_mib() -> float | None:
    """Dedicated GPU memory currently in use, via nvidia-smi."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15, check=True,
        )
        return float(out.stdout.strip().splitlines()[0])
    except Exception:
        return None


def ollama_ps() -> str:
    try:
        return subprocess.run(
            ["ollama", "ps"], capture_output=True, text=True, timeout=30
        ).stdout
    except Exception:
        return ""


def gpu_placement(model: str) -> str:
    """Parse `ollama ps` for the PROCESSOR column of this model."""
    for line in ollama_ps().splitlines():
        if not line.startswith(model.split(":")[0]):
            continue
        if re.search(r"100%\s*GPU", line):
            return "100% GPU"
        m = re.search(r"(\d+)%\s*/\s*(\d+)%\s*CPU\s*/\s*GPU", line)
        if m:
            return f"{m.group(1)}% CPU / {m.group(2)}% GPU  <-- SPILL"
        if "CPU" in line:
            return "CPU involved  <-- SPILL"
    return "unknown"


def unload(model: str) -> None:
    try:
        post("/api/generate", {"model": model, "keep_alive": 0}, timeout=60)
    except Exception:
        pass
    time.sleep(3)


def extract_json(text: str) -> dict | None:
    """Models wrap JSON in prose or fences. Pull out the first object."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"```(?:json)?", "", text)
    depth, start = 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    start = None
    return None


def extract_json_from_result(out: dict) -> dict | None:
    """
    Some thinking-enabled models (e.g. qwen3-vl) put the entire answer in the
    separate `thinking` field and leave `response` empty, even under
    format="json". Try `response` first; fall back to `thinking` so those
    models aren't scored as if they produced nothing.
    """
    obj = extract_json(out.get("response", ""))
    if obj is not None:
        return obj
    return extract_json(out.get("thinking", ""))


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------
@dataclass
class Result:
    model: str
    slot: str
    context: int
    budget_s: float
    available: bool = False
    cold_load_s: float | None = None
    ttft_s: list[float] = field(default_factory=list)
    tok_per_s: list[float] = field(default_factory=list)
    total_s: list[float] = field(default_factory=list)
    peak_vram_mib: float | None = None
    baseline_vram_mib: float | None = None
    placement: str = "unknown"
    structured_pass: int = 0
    structured_total: int = 0
    tool_pass: int = 0
    tool_total: int = 0
    starts_clean: int = 0
    error: str = ""

    @property
    def med_ttft(self):
        return statistics.median(self.ttft_s) if self.ttft_s else None

    @property
    def med_tps(self):
        return statistics.median(self.tok_per_s) if self.tok_per_s else None

    @property
    def med_total(self):
        return statistics.median(self.total_s) if self.total_s else None

    def verdict(self) -> tuple[bool, list[str]]:
        """Blueprint 6.5 keep rule. Returns (keep, reasons_for_failure)."""
        fails = []
        if not self.available:
            return False, ["model not installed or failed to load"]
        if "SPILL" in self.placement:
            fails.append(f"spills to system memory ({self.placement})")
        if self.starts_clean < 3:
            fails.append(f"started cleanly only {self.starts_clean}/3 times")
        if self.med_total is not None and self.med_total > self.budget_s:
            fails.append(f"median {self.med_total:.1f}s exceeds {self.budget_s:.0f}s budget")
        if self.structured_total:
            # Blueprint 6.5: "valid structured output in at least 4 of 5 test
            # cases" = 80%. Kept proportional so slots with a different task
            # count (e.g. vision's 2 image tasks) use the same bar, not a
            # literal "4" that a smaller task list could never reach.
            min_required = math.ceil(0.8 * self.structured_total)
            if self.structured_pass < min_required:
                fails.append(
                    f"structured output {self.structured_pass}/{self.structured_total}, "
                    f"need {min_required}/{self.structured_total}"
                )
        return (len(fails) == 0), fails


# ---------------------------------------------------------------------------
# Benchmark one model
# ---------------------------------------------------------------------------
def bench(model: str, slot: str, ctx: int, budget: float, runs: int, is_vision: bool) -> Result:
    r = Result(model=model, slot=slot, context=ctx, budget_s=budget)
    print(f"\n{'=' * 66}\n  {model}   [{slot}, ctx={ctx}]\n{'=' * 66}")

    # Confirm installed
    try:
        tags = json.loads(urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=30).read())
        installed = {m["name"] for m in tags.get("models", [])}
        if model not in installed and f"{model}:latest" not in installed:
            r.error = "not installed"
            print(f"  [!] not installed -- run: ollama pull {model}")
            return r
    except Exception as exc:
        r.error = f"cannot reach ollama: {exc}"
        print(f"  [!] {r.error}")
        return r

    r.available = True
    unload(model)
    r.baseline_vram_mib = gpu_used_mib()
    print(f"  baseline VRAM: {r.baseline_vram_mib:.0f} MiB" if r.baseline_vram_mib else "  baseline VRAM: n/a")

    # --- cold load ---
    print("  [1/5] cold load ...", end=" ", flush=True)
    t0 = time.perf_counter()
    try:
        post("/api/generate", {
            "model": model, "prompt": "ok", "stream": False,
            "options": {"num_ctx": ctx, "num_predict": 1, "temperature": 0},
        })
        r.cold_load_s = time.perf_counter() - t0
        print(f"{r.cold_load_s:.1f}s")
    except Exception as exc:
        r.error = f"cold load failed: {exc}"
        print(f"FAILED: {exc}")
        return r

    r.placement = gpu_placement(model)
    print(f"  placement: {r.placement}")

    # --- throughput, repeated ---
    print(f"  [2/5] generation x{runs} ...")
    prompt = ("Draft a two-paragraph approval note for a low-severity seal weep "
              "found on pump P-104 during routine inspection. Cite the source page.")
    for i in range(runs):
        peak = r.baseline_vram_mib or 0
        first_tok, count, last = None, 0, 0.0
        try:
            for elapsed, chunk in post_stream("/api/generate", {
                "model": model, "prompt": prompt, "stream": True,
                "options": {"num_ctx": ctx, "num_predict": 300, "temperature": 0.2},
            }):
                if chunk.get("response"):
                    if first_tok is None:
                        first_tok = elapsed
                    count += 1
                last = elapsed
                if count % 40 == 1:
                    cur = gpu_used_mib()
                    if cur:
                        peak = max(peak, cur)
                if chunk.get("done"):
                    # Ollama reports authoritative token counts; prefer them
                    ec = chunk.get("eval_count")
                    ed = chunk.get("eval_duration")
                    if ec and ed:
                        r.tok_per_s.append(ec / (ed / 1e9))
                    elif count and last:
                        r.tok_per_s.append(count / last)
                    break
        except Exception as exc:
            print(f"    run {i + 1}: FAILED {exc}")
            continue

        r.starts_clean += 1
        if first_tok:
            r.ttft_s.append(first_tok)
        r.total_s.append(last)
        r.peak_vram_mib = max(r.peak_vram_mib or 0, peak)
        ttft_str = f"{first_tok:.2f}s" if first_tok is not None else "n/a"
        if r.tok_per_s:
            print(f"    run {i + 1}: ttft={ttft_str}  total={last:.1f}s  tps={r.tok_per_s[-1]:.1f}")
        else:
            print(f"    run {i + 1}: done")

    # --- structured output ---
    # Vision slot gets real image tasks (its actual job); reasoning/coding
    # keep the shared text-only STRUCTURED_TASKS, unchanged.
    tasks = VISION_TASKS if is_vision else STRUCTURED_TASKS
    print(f"  [3/5] structured output ({len(tasks)} tasks) ...", end=" ", flush=True)
    for task in tasks:
        r.structured_total += 1
        try:
            if is_vision:
                name, prompt_s, keys, image_path = task
                image_b64 = base64.b64encode(Path(image_path).read_bytes()).decode()
                payload = {
                    "model": model, "prompt": prompt_s, "stream": False, "format": "json",
                    "images": [image_b64],
                    "options": {"num_ctx": ctx, "num_predict": 400, "temperature": 0},
                }
            else:
                name, prompt_s, keys = task
                payload = {
                    "model": model, "prompt": prompt_s, "stream": False, "format": "json",
                    "options": {"num_ctx": ctx, "num_predict": 400, "temperature": 0},
                }
            out = post("/api/generate", payload)
            obj = extract_json_from_result(out)
            if obj and keys.issubset(set(obj.keys())):
                r.structured_pass += 1
        except Exception:
            pass
    print(f"{r.structured_pass}/{r.structured_total}")

    # --- tool calling (skip for vision slot) ---
    if not is_vision:
        print("  [4/5] tool calling (5 tasks) ...", end=" ", flush=True)
        for tp in TOOL_PROMPTS:
            r.tool_total += 1
            try:
                out = post("/api/chat", {
                    "model": model,
                    "messages": [{"role": "user", "content": tp}],
                    "tools": TOOL_SCHEMA,
                    "stream": False,
                    "options": {"num_ctx": ctx, "temperature": 0},
                })
                if out.get("message", {}).get("tool_calls"):
                    r.tool_pass += 1
            except Exception:
                pass
        print(f"{r.tool_pass}/{r.tool_total}")
    else:
        print("  [4/5] tool calling: skipped for vision slot")

    # --- peak VRAM settle ---
    print("  [5/5] peak VRAM ...", end=" ", flush=True)
    cur = gpu_used_mib()
    if cur:
        r.peak_vram_mib = max(r.peak_vram_mib or 0, cur)
    print(f"{r.peak_vram_mib:.0f} MiB" if r.peak_vram_mib else "n/a")

    unload(model)
    return r


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def write_report(results: list[Result], out_path: Path, runs: int) -> None:
    L = []
    A = L.append
    A("# SETU Benchmark Results\n")
    A(f"**Captured:** {datetime.now(timezone.utc).isoformat(timespec='seconds')}  ")
    A("**Machine:** NVIDIA RTX 4060 Laptop GPU, 8 GB VRAM  ")
    A(f"**Runs per model:** {runs}  ")
    A("**Gate:** blueprint section 6.5\n")

    total_vram = None
    try:
        o = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total",
                            "--format=csv,noheader"], capture_output=True, text=True, timeout=15)
        total_vram = o.stdout.strip()
    except Exception:
        pass
    if total_vram:
        A(f"**GPU reported:** {total_vram}\n")

    A("## Measurements\n")
    A("| Model | Slot | Cold load | TTFT (med) | tok/s (med) | Total (med) | Peak VRAM | Placement | Structured | Tools |")
    A("|---|---|---:|---:|---:|---:|---:|---|---:|---:|")
    for r in results:
        if not r.available:
            A(f"| `{r.model}` | {r.slot} | — | — | — | — | — | not installed | — | — |")
            continue
        A("| `{m}` | {s} | {cl} | {tt} | {tp} | {to} | {vr} | {pl} | {sp}/{st} | {tlp}{tlt} |".format(
            m=r.model, s=r.slot,
            cl=f"{r.cold_load_s:.1f}s" if r.cold_load_s else "—",
            tt=f"{r.med_ttft:.2f}s" if r.med_ttft else "—",
            tp=f"{r.med_tps:.1f}" if r.med_tps else "—",
            to=f"{r.med_total:.1f}s" if r.med_total else "—",
            vr=f"{r.peak_vram_mib:.0f} MiB" if r.peak_vram_mib else "—",
            pl=r.placement,
            sp=r.structured_pass, st=r.structured_total,
            tlp=f"{r.tool_pass}/" if r.tool_total else "n/a",
            tlt=f"{r.tool_total}" if r.tool_total else "",
        ))

    A("\n## Gate decisions\n")
    by_slot: dict[str, list[Result]] = {}
    for r in results:
        by_slot.setdefault(r.slot, []).append(r)

    chosen: dict[str, str] = {}
    for slot, rs in by_slot.items():
        A(f"### {slot}\n")
        for r in rs:
            keep, fails = r.verdict()
            A(f"- **`{r.model}`** — {'KEEP' if keep else 'REJECT'}")
            for f in fails:
                A(f"  - {f}")
        winner = next((r.model for r in rs if r.verdict()[0]), None)
        if winner:
            chosen[slot] = winner
            A(f"\n**Selected: `{winner}`**\n")
        else:
            A("\n**No candidate passed. Investigate before T-3, or reduce context and re-run.**\n")

    A("## Frozen registry values\n")
    A("Copy into `config/models.yaml`:\n")
    A("```yaml")
    for slot, model in chosen.items():
        ctx = next(r.context for r in by_slot[slot] if r.model == model)
        A(f"{slot}-primary:")
        A(f"  model: {model}")
        A(f"  context_limit: {ctx}")
        A("  keep_alive: 10m")
    A("```\n")
    A("> Blueprint: no model changes after T-3 except an emergency rollback with a recorded reason.\n")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(L), encoding="utf-8")
    print(f"\n[+] wrote {out_path}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO_ROOT / "docs" / "BENCHMARKS.md"))
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--only", help="benchmark a single model tag")
    ap.add_argument("--only-slot", help="benchmark only this slot's primary+fallback (e.g. vision)")
    ap.add_argument("--primaries-only", action="store_true")
    args = ap.parse_args()

    try:
        urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=10)
    except Exception:
        print(f"[!] Ollama unreachable at {OLLAMA}. Start it and re-run.")
        return 1

    print("Close Chrome, Discord, Teams and any Electron app before continuing.")
    print("Browser VRAM use is the most common cause of a false spill result.")
    input("Press Enter when ready ...")

    results: list[Result] = []
    for slot, primary, fallback, ctx, budget in SLOTS:
        if args.only_slot and slot != args.only_slot:
            continue
        candidates = [primary] if args.primaries_only else [primary, fallback]
        for model in candidates:
            if args.only and model != args.only:
                continue
            results.append(bench(model, slot, ctx, budget, args.runs, slot == "vision"))

    write_report(results, Path(args.out), args.runs)

    print("\n" + "=" * 66)
    for r in results:
        keep, fails = r.verdict()
        print(f"  {'KEEP  ' if keep else 'REJECT'}  {r.model:<24} {r.placement}")
        for f in fails:
            print(f"            - {f}")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
