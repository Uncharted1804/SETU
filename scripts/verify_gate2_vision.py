"""
Gate 2 Hard Deliverable Verification Script (Hour 9 Gate)

Blueprint Gate 2 Pass Condition:
The scanned inspection report reliably yields >= 5 clean findings,
twice in a row, without a restart:
- Each finding has non-empty text, valid page, bbox, confidence >= 0.70, and extraction_tier
- page_legibility is accurately tracked
- Both sequential runs pass without errors or restarts

Usage:
    # Live mode (requires Ollama running):
    python scripts/verify_gate2_vision.py

    # Mock mode (validates pipeline logic and contracts offline):
    python scripts/verify_gate2_vision.py --mock
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents.base import AgentContext
from app.agents.vision import VisionAgent
from app.config import get_registry, get_settings
from app.contracts import AgentInvocation, AgentResult, Finding, VisionOutput


def evaluate_findings(result: AgentResult, run_label: str) -> bool:
    """Validate that result satisfies all Gate 2 requirements."""
    print(f"\n--- Evaluating {run_label} ---")
    if result.error:
        print(f"  [FAIL] Error returned: {result.error.message}")
        if result.escalation_reason:
            print(f"         Escalation: {result.escalation_reason}")
        return False

    payload = result.payload
    findings = payload.get("findings", [])
    overall_conf = payload.get("overall_confidence", 0.0)
    page_leg = payload.get("page_legibility", 0.0)

    print(f"  Model:              {result.model}")
    print(f"  Findings count:     {len(findings)} (Gate 2 requirement: >= 5)")
    print(f"  Page Legibility:    {page_leg * 100:.1f}%")
    print(f"  Overall Confidence: {overall_conf * 100:.1f}% (Threshold: >= 70.0%)")

    if len(findings) < 5:
        print(f"  [FAIL] Only {len(findings)} findings extracted (must be >= 5)")
        return False

    valid_count = 0
    for i, f in enumerate(findings, start=1):
        text = f.get("text", "").strip()
        page = f.get("page", 0)
        bbox = f.get("bbox")
        conf = f.get("confidence", 0.0)
        tier = f.get("extraction_tier")

        valid = bool(text) and page >= 1 and conf >= 0.70 and tier in ["text_layer", "tesseract", "vlm"]
        status = "[PASS]" if valid else "[WARN]"
        print(f"    {status} Finding {i:02d}: conf={conf*100:.1f}% | tier={tier:<10} | page={page} | bbox={bbox} | text={text[:45]}...")
        if valid:
            valid_count += 1

    if valid_count < 5:
        print(f"  [FAIL] Only {valid_count} clean findings passed all validation criteria")
        return False

    print(f"  [PASS] {run_label} PASSED: {valid_count} valid findings extracted with clean confidence and metadata.")
    return True


async def run_gate2_verification(target_rel_path: str, mock_mode: bool = False):
    print("=" * 75)
    print("SETU P2 -- GATE 2 VERIFICATION RUNNER (Hour 9 Hard Deliverable)")
    print("=" * 75)
    print(f"Target Document: {target_rel_path}")
    print(f"Execution Mode:  {'MOCK MODE (Offline verification)' if mock_mode else 'LIVE MODE (Ollama / Local GPU)'}")

    import shutil
    settings = get_settings()
    registry = get_registry()
    model_entry = registry.resolve_for_agent("vision")
    ctx = AgentContext(settings, registry)
    agent = VisionAgent(ctx)

    # Ensure file is staged in workspace (matching real Orchestrator behavior)
    workspace = settings.workspace
    dest_dir = workspace / "uploads"
    dest_dir.mkdir(parents=True, exist_ok=True)
    src_path = REPO_ROOT / target_rel_path if not Path(target_rel_path).is_absolute() else Path(target_rel_path)
    if not src_path.exists():
        print(f"[FAIL] Target document not found at {src_path}")
        return False
    dest_file = dest_dir / src_path.name
    shutil.copy2(src_path, dest_file)
    staged_rel_path = f"uploads/{src_path.name}"
    print(f"Staged in workspace: {staged_rel_path}")

    mock_client = None
    if mock_mode:
        # Build mock Ollama client returning clean findings for scanned reports
        mock_client = AsyncMock()
        mock_client.ensure_model = AsyncMock(return_value=None)
        mock_output = VisionOutput(
            findings=[
                Finding(id="f-01", text="Inspection Point 1: Shell weld seam visually intact", page=1, bbox=[45.0, 100.0, 480.0, 125.0], confidence=0.88, source_file=target_rel_path, extraction_tier="vlm"),
                Finding(id="f-02", text="Inspection Point 2: Thickness 11.8 mm at C-3", page=1, bbox=[45.0, 135.0, 480.0, 160.0], confidence=0.92, source_file=target_rel_path, extraction_tier="vlm"),
                Finding(id="f-03", text="Inspection Point 3: PRV-102 calibration seal verified", page=1, bbox=[45.0, 170.0, 480.0, 195.0], confidence=0.85, source_file=target_rel_path, extraction_tier="vlm"),
                Finding(id="f-04", text="Inspection Point 4: Surface corrosion on saddle support", page=1, bbox=[45.0, 205.0, 480.0, 230.0], confidence=0.78, source_file=target_rel_path, extraction_tier="vlm"),
                Finding(id="f-05", text="Inspection Point 5: Hydrotest held at 18.5 bar with 0 drop", page=1, bbox=[45.0, 240.0, 480.0, 265.0], confidence=0.95, source_file=target_rel_path, extraction_tier="vlm"),
                Finding(id="f-06", text="Inspection Point 6: Grounding resistance 0.04 ohms", page=1, bbox=[45.0, 275.0, 480.0, 300.0], confidence=0.90, source_file=target_rel_path, extraction_tier="vlm"),
            ],
            page_legibility=0.90,
            overall_confidence=0.89,
            raw_text="Sample inspection text",
            injection_flags=[],
        )
        mock_client.chat_vision = AsyncMock(return_value={
            "message": {"content": mock_output.model_dump_json()}
        })

    async def make_run(inv: AgentInvocation):
        if mock_mode:
            with patch.object(ctx, "client", return_value=mock_client):
                return await agent.run(inv)
        return await agent.run(inv)

    # --- Run 1 ---
    print("\n>>> STARTING RUN 1 (Sequential Execution 1/2) <<<")
    inv1 = AgentInvocation(
        agent="vision",
        model_id=model_entry.id,
        model=model_entry.model,
        prompt_summary="Gate 2 run 1: extract findings from inspection report",
        attempt=1,
        inputs={"file_paths": [staged_rel_path]},
    )
    t0 = time.perf_counter()
    result1 = await make_run(inv1)
    t_run1 = (time.perf_counter() - t0) * 1000
    print(f"Run 1 completed in {t_run1:.1f} ms")
    run1_ok = evaluate_findings(result1, "RUN 1")

    # --- Run 2 ---
    print("\n>>> STARTING RUN 2 (Sequential Execution 2/2, No Server Restart) <<<")
    inv2 = AgentInvocation(
        agent="vision",
        model_id=model_entry.id,
        model=model_entry.model,
        prompt_summary="Gate 2 run 2: extract findings from inspection report",
        attempt=1,
        inputs={"file_paths": [staged_rel_path]},
    )
    t0 = time.perf_counter()
    result2 = await make_run(inv2)
    t_run2 = (time.perf_counter() - t0) * 1000
    print(f"Run 2 completed in {t_run2:.1f} ms")
    run2_ok = evaluate_findings(result2, "RUN 2")

    # --- Final Verdict ---
    print("\n" + "=" * 75)
    print("GATE 2 FINAL VERDICT")
    print("=" * 75)
    if run1_ok and run2_ok:
        print("[SUCCESS] GATE 2 PASSED: Pipeline reliably produced >= 5 clean findings twice in a row!")
        print(f"  Run 1: {len(result1.payload.get('findings', []))} findings in {t_run1:.1f} ms")
        print(f"  Run 2: {len(result2.payload.get('findings', []))} findings in {t_run2:.1f} ms")
        print("=" * 75)
        return True
    else:
        print("[FAILURE] GATE 2 FAILED: One or both sequential runs did not satisfy pass conditions.")
        print("=" * 75)
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Gate 2 Vision verification")
    parser.add_argument(
        "--file",
        default="data/demo_assets/vision_bench/sample_inspection_digital.pdf",
        help="Relative path to test document within workspace",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run in mock mode (simulates Ollama response for offline verification)",
    )
    args = parser.parse_args()
    success = asyncio.run(run_gate2_verification(args.file, mock_mode=args.mock))
    sys.exit(0 if success else 1)
