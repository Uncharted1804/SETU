"""
Vision agent.  OWNER: P2.

Job: extract text and findings from scans, photos, handwriting and engineering
drawings.  Model: resolved from config/models.yaml capability "vision".

Confidence signal: TWO numbers, deliberately - the model's self-reported score
AND how much of the page was legible.  Threshold 0.70, 3 attempts.
MAX_ATTEMPTS["vision"] = 3 is owned by config.py; Vision reads it, never
redefines it.

RETRY ARCHITECTURE (P1 owns the attempt loop):
  The orchestration/executor.py runs the attempt loop up to MAX_ATTEMPTS["vision"].
  It calls agent.run(inv) once per attempt, passing inv.attempt (1-indexed) and
  inv.feedback (the failure reason from the previous attempt).
  Vision cooperates with P1 by:
    - attempt 1: running the full three-tier cascade.
    - attempt 2+: running a targeted retry (crop the lowest-confidence finding's
      bbox, enhance, VLM only that region) and merging back into the prior result.
  Prior findings reach Vision via inv.inputs["prior"] (the last 3 observations
  relayed by the orchestrator); Vision extracts them from the most recent vision
  observation payload.

RETRY MUST PRESERVE OTHER FINDINGS (blueprint requirement):
  Attempt 1:  A B C D E   (C is lowest confidence)
  Retry C.
  Attempt 2:  C'
  Final:      A B C' D E  (not just C')
  If C' is worse than C, keep C.  Never discard A, B, D, E.

THREE-TIER CASCADE:
  Tier 1 (text_layer): PyMuPDF block extraction for digital PDFs.  Exact, ~50 ms.
  Tier 2 (tesseract):  Tesseract for clean scanned print. ~1 s/page, CPU.
  Tier 3 (vlm):        VLM for handwriting, drawings, tables, low-confidence
                       regions.  GPU, structured JSON output.

SCOPE LIMIT (blueprint F11):
  Vision EXTRACTS visible labels, text, annotations, dimensions and callouts.
  It does NOT interpret or approve engineering drawings.
  Engineering judgment, compliance decisions and safety rulings escalate to human.

OUTPUT BOUNDARY:
  Vision produces VisionOutput.  It does not call the reasoning agent.
  It does not call the coding agent.  Output flows to the P1 orchestrator.

P3 owns injection_flags: Vision leaves the field empty.  P3 performs its scan
on the findings payload downstream.
"""

from __future__ import annotations

import json
import secrets
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from ..config import MAX_ATTEMPTS, THRESHOLDS, VISION_EXTS
from ..contracts import (
    AgentInvocation,
    AgentResult,
    Attempt,
    ErrorCode,
    Finding,
    StructuredError,
    VisionOutput,
)
from ..llm.ollama_client import OllamaError
from ..tools.base import ToolError
from ..tools.ocr import (
    cascade_plan,
    crop_to_bbox,
    has_text_layer,
    mean_confidence,
    preprocess,
    rasterize,
    tier1_text_layer,
    tier2_tesseract,
)
from .base import AgentContext

# Vision threshold – owned by config.py, read here for clarity.
_THRESHOLD = THRESHOLDS["vision"]  # 0.70

# VLM inference options (blueprint section 4.3 / shared Ollama environment).
_VLM_OPTIONS: dict[str, Any] = {
    "num_ctx": 4096,
    "temperature": 0.1,
    "num_predict": 768,
}

# Extraction tier used for VLM findings in this agent.
_VLM_TIER = "vlm"

# Prompt for the initial (full-page) VLM extraction.
_SYSTEM_PROMPT_VISION = (
    "You are a document extraction system. "
    "Extract all visible text, labels, annotations, dimensions, callouts, and "
    "handwritten remarks from the provided image. "
    "Do NOT interpret engineering meaning, judge compliance, or make safety decisions. "
    "For each piece of extracted text, provide: "
    "  - text: the exact visible text "
    "  - page: the page number (provided separately) "
    "  - bbox: bounding box [x0, y0, x1, y1] in pixels if visible, or null "
    "  - confidence: your extraction confidence as a float in [0.0, 1.0] "
    "  - extraction_tier: always \"vlm\" "
    "Report only what is visibly present. Do not fabricate text or confidence values. "
    "Be honest if a region is unclear."
)

# Prompt for targeted retry of a specific low-confidence region.
_RETRY_PROMPT_TEMPLATE = (
    "TARGETED RETRY — previous extraction attempt had low confidence.\n"
    "Page number: {page}\n"
    "Previous failure: {failure}\n"
    "The image provided is a CROPPED REGION of the original page — not the full page.\n"
    "Extract all visible text, labels, annotations, and handwritten content from this "
    "cropped region only.\n"
    "Do NOT re-read or assume context from the full page.\n"
    "Do NOT interpret engineering meaning or judge compliance.\n"
    "Provide honest confidence. Do not inflate confidence.\n"
    "bbox coordinates should be relative to this cropped image."
)


def format_findings_text(findings: list[Finding]) -> str:
    """Reconstruct natural lines and paragraphs from findings.

    Prevents single-word findings (e.g. from Tesseract) from turning into one
    word per line, grouping words by line based on bboxes and spacing.
    """
    if not findings:
        return ""
    # If findings already contain spaces or multi-line strings, preserve block structure
    has_blocks = any(" " in (f.text or "").strip() for f in findings)
    if has_blocks:
        return "\n\n".join(f.text.strip() for f in findings if (f.text or "").strip())

    lines: list[list[str]] = []
    current_line: list[str] = []
    last_page: Optional[int] = None
    last_y: Optional[float] = None
    last_h: Optional[float] = None

    for f in findings:
        text = (f.text or "").strip()
        if not text:
            continue
        if f.bbox and len(f.bbox) == 4:
            y_mid = (f.bbox[1] + f.bbox[3]) / 2.0
            h = max(1.0, f.bbox[3] - f.bbox[1])
            is_same_line = (
                last_page == f.page
                and last_y is not None
                and abs(y_mid - last_y) <= max(8.0, (last_h or h) * 0.6)
            )
            if is_same_line:
                current_line.append(text)
            else:
                if current_line:
                    lines.append(current_line)
                current_line = [text]
                last_page = f.page
                last_y = y_mid
                last_h = h
        else:
            current_line.append(text)

    if current_line:
        lines.append(current_line)

    return "\n".join(" ".join(words) for words in lines)


class VisionAgent:
    name = "vision"

    def __init__(self, ctx: AgentContext) -> None:
        self.ctx = ctx

    async def run(self, inv: AgentInvocation) -> AgentResult:
        t_start = time.perf_counter()

        # -- 1. Resolve model from config/models.yaml -------------------------
        entry = self.ctx.model_for("vision")

        # -- 2. Get file path(s) from the orchestrator relay ------------------
        # P1 relays: inputs = {"why": step.why, "args": step.args, "prior": [...], "file_paths": [...]}
        args = inv.inputs.get("args") or {}
        file_paths: list[str] = (
            args.get("file_paths")
            or args.get("input_paths")
            or args.get("paths")
            or args.get("files")
            or args.get("image_paths")
            or args.get("images")
            or inv.inputs.get("file_paths")
            or []
        )

        # Also accept a single path
        if not file_paths and (
            args.get("file_path")
            or args.get("input_path")
            or args.get("path")
            or args.get("image_path")
            or inv.inputs.get("file_path")
        ):
            single = (
                args.get("file_path")
                or args.get("input_path")
                or args.get("path")
                or args.get("image_path")
                or inv.inputs.get("file_path")
            )
            if single:
                file_paths = [single]

        # Task file_paths may also come from the task envelope via prior
        if not file_paths:
            prior = inv.inputs.get("prior") or []
            for obs in reversed(prior):
                if obs.get("target") == "vision":
                    pf = (obs.get("payload") or {}).get("_file_paths")
                    if pf:
                        file_paths = pf
                        break

        if not file_paths:
            duration_ms = round((time.perf_counter() - t_start) * 1000, 1)
            error = StructuredError(
                code=ErrorCode.INVALID_ARGS,
                message="VisionAgent: no file_paths provided in task inputs.",
                detail={"inputs_keys": list(inv.inputs.keys())},
            )
            return AgentResult(
                agent="vision",
                model=entry.model,
                payload={},
                attempts=[Attempt(n=inv.attempt, confidence=0.0,
                                  failure_reason="no file_paths in inputs",
                                  duration_ms=duration_ms)],
                final_confidence=0.0,
                needs_human_review=True,
                escalation_reason="no file_paths in task inputs",
                error=error,
            )

        # Use the first file for this invocation (P1 dispatches one step per file).
        source_rel = file_paths[0]

        # For retries (attempt >= 2), prior findings are required.
        # Check this before connecting to client so missing prior findings
        # immediately return INVALID_ARGS without attempting client connections.
        if inv.attempt >= 2:
            prior_findings = self._extract_prior_findings(inv)
            if not prior_findings:
                duration_ms = round((time.perf_counter() - t_start) * 1000, 1)
                error = StructuredError(
                    code=ErrorCode.INVALID_ARGS,
                    message="VisionAgent: attempt %d requires prior findings to retry." % inv.attempt,
                    detail={"attempt": inv.attempt},
                )
                return AgentResult(
                    agent="vision",
                    model=entry.model,
                    payload={},
                    attempts=[Attempt(n=inv.attempt, confidence=0.0,
                                      failure_reason="no prior findings for retry",
                                      feedback_injected=inv.feedback,
                                      duration_ms=duration_ms)],
                    final_confidence=0.0,
                    needs_human_review=True,
                    escalation_reason="no prior findings for targeted retry",
                    error=error,
                )

        # -- 3. Ensure model is available (never pulls) -----------------------
        client = self.ctx.client()
        try:
            await client.ensure_model(entry.model)
        except OllamaError as exc:
            duration_ms = round((time.perf_counter() - t_start) * 1000, 1)
            return AgentResult(
                agent="vision",
                model=entry.model,
                payload={"_file_paths": file_paths},
                attempts=[Attempt(n=inv.attempt, confidence=0.0,
                                  failure_reason=str(exc),
                                  feedback_injected=inv.feedback,
                                  duration_ms=duration_ms)],
                final_confidence=0.0,
                needs_human_review=True,
                escalation_reason="vision model not available: %s" % exc,
                error=exc.as_error(),
            )

        # -- 4. Route by attempt number ---------------------------------------
        if inv.attempt == 1:
            return await self._attempt_full_cascade(
                inv, entry, client, source_rel, file_paths, t_start
            )
        else:
            return await self._attempt_targeted_retry(
                inv, entry, client, source_rel, file_paths, t_start
            )

    # -------------------------------------------------------------------------
    # Full cascade (attempt 1)
    # -------------------------------------------------------------------------

    async def _attempt_full_cascade(
        self,
        inv: AgentInvocation,
        entry,
        client,
        source_rel: str,
        file_paths: list[str],
        t_start: float,
    ) -> AgentResult:
        settings = self.ctx.settings
        workspace = settings.workspace
        file_path = workspace / source_rel
        suffix = file_path.suffix.lower().lstrip(".")
        all_findings: list[Finding] = []
        raw_text_parts: list[str] = []
        page_legibility: float = 0.0

        try:
            if suffix == "pdf":
                # -- Tier 1: text layer for digital PDFs ----------------------
                if has_text_layer(file_path):
                    t1_findings = tier1_text_layer(file_path, source_rel)
                    all_findings.extend(t1_findings)
                    raw_text_parts.extend(f.text for f in t1_findings)
                    page_legibility = 1.0 if t1_findings else 0.5
                    # Tier 1 alone is sufficient for clean digital PDFs
                    # but we also rasterize pages with no text layer for Tier 2
                    # We do this by checking per-page; for simplicity when the
                    # document has a text layer, we trust Tier 1 and skip VLM.
                    # No VLM on clean digital pages (blueprint requirement).
                else:
                    # No text layer: rasterize and send to Tier 2 / Tier 3
                    with tempfile.TemporaryDirectory(prefix="setu_ocr_") as tmp:
                        tmp_path = Path(tmp)
                        page_images = rasterize(file_path, tmp_path, dpi=300)
                        tier2_findings_all: list[Finding] = []
                        for page_idx, img_path in enumerate(page_images):
                            page_num = page_idx + 1
                            t2_findings = tier2_tesseract(img_path, source_rel, page_num)
                            tier2_findings_all.extend(t2_findings)

                        mean_t2 = mean_confidence(tier2_findings_all)
                        tier = cascade_plan(False, mean_t2 if tier2_findings_all else None)

                        if tier == "vlm" or not tier2_findings_all:
                            # Send to Tier 3: VLM
                            vlm_findings = await self._run_vlm_on_pages(
                                client, entry, page_images, source_rel,
                                prompt=_SYSTEM_PROMPT_VISION,
                            )
                            all_findings.extend(vlm_findings)
                            raw_text_parts.extend(f.text for f in vlm_findings)
                        else:
                            all_findings.extend(tier2_findings_all)
                            raw_text_parts.extend(f.text for f in tier2_findings_all)

                        page_legibility = (
                            mean_confidence(all_findings) if all_findings else 0.0
                        )

            elif suffix in VISION_EXTS:
                # Direct image input: skip Tier 1, start at Tier 2
                with tempfile.TemporaryDirectory(prefix="setu_ocr_") as tmp:
                    tmp_path = Path(tmp)
                    page_num = 1
                    try:
                        t2_findings = tier2_tesseract(file_path, source_rel, page_num)
                    except ToolError:
                        t2_findings = []

                    mean_t2 = mean_confidence(t2_findings)
                    tier = cascade_plan(False, mean_t2 if t2_findings else None)

                    if tier == "vlm" or not t2_findings:
                        vlm_findings = await self._run_vlm_on_pages(
                            client, entry, [file_path], source_rel,
                            prompt=_SYSTEM_PROMPT_VISION,
                        )
                        all_findings.extend(vlm_findings)
                        raw_text_parts.extend(f.text for f in vlm_findings)
                    else:
                        all_findings.extend(t2_findings)
                        raw_text_parts.extend(f.text for f in t2_findings)

                    page_legibility = mean_confidence(all_findings) if all_findings else 0.0

            else:
                duration_ms = round((time.perf_counter() - t_start) * 1000, 1)
                error = StructuredError(
                    code=ErrorCode.INVALID_ARGS,
                    message="VisionAgent: unsupported file extension .%s" % suffix,
                    detail={"source_file": source_rel, "extension": suffix},
                )
                return AgentResult(
                    agent="vision",
                    model=entry.model,
                    payload={"_file_paths": file_paths},
                    attempts=[Attempt(n=inv.attempt, confidence=0.0,
                                      failure_reason="unsupported extension: .%s" % suffix,
                                      feedback_injected=inv.feedback,
                                      duration_ms=duration_ms)],
                    final_confidence=0.0,
                    needs_human_review=True,
                    escalation_reason="unsupported file extension: .%s" % suffix,
                    error=error,
                )

        except ToolError as exc:
            duration_ms = round((time.perf_counter() - t_start) * 1000, 1)
            return AgentResult(
                agent="vision",
                model=entry.model,
                payload={"_file_paths": file_paths},
                attempts=[Attempt(n=inv.attempt, confidence=0.0,
                                  failure_reason=exc.message,
                                  feedback_injected=inv.feedback,
                                  duration_ms=duration_ms)],
                final_confidence=0.0,
                needs_human_review=True,
                escalation_reason="OCR cascade failed: %s" % exc.message,
                error=exc.as_error(),
            )
        except OllamaError as exc:
            duration_ms = round((time.perf_counter() - t_start) * 1000, 1)
            return AgentResult(
                agent="vision",
                model=entry.model,
                payload={"_file_paths": file_paths},
                attempts=[Attempt(n=inv.attempt, confidence=0.0,
                                  failure_reason=str(exc),
                                  feedback_injected=inv.feedback,
                                  duration_ms=duration_ms)],
                final_confidence=0.0,
                needs_human_review=True,
                escalation_reason="VLM call failed: %s" % exc,
                error=exc.as_error(),
            )

        # -- Compute confidence signals ----------------------------------------
        avg_finding_conf = mean_confidence(all_findings) if all_findings else 0.0
        overall_confidence = (avg_finding_conf + page_legibility) / 2.0
        overall_confidence = max(0.0, min(1.0, overall_confidence))

        # -- Determine needs_human_review and failure_reason ------------------
        failure_reason: Optional[str] = None
        needs_review = False
        escalation_reason: Optional[str] = None

        if overall_confidence < _THRESHOLD:
            failure_reason = (
                "overall confidence %.2f is below threshold %.2f; "
                "%d findings extracted" % (overall_confidence, _THRESHOLD, len(all_findings))
            )
            # Human review only on the final attempt (P1 decides to escalate).
            # On intermediate attempts, P1 will retry us.

        # If we have no findings at all after all tiers, that's a clear failure
        if not all_findings:
            failure_reason = "no text could be extracted from %s" % source_rel

        # Build VisionOutput
        vision_output = VisionOutput(
            findings=all_findings,
            page_legibility=page_legibility,
            overall_confidence=overall_confidence,
            raw_text=format_findings_text(all_findings),
            injection_flags=[],  # P3 populates this downstream
        )

        duration_ms = round((time.perf_counter() - t_start) * 1000, 1)
        attempt_rec = Attempt(
            n=inv.attempt,
            confidence=overall_confidence,
            failure_reason=failure_reason,
            feedback_injected=inv.feedback,
            duration_ms=duration_ms,
        )

        payload = vision_output.model_dump()
        payload["_file_paths"] = file_paths
        payload["_summary"] = (
            "vision extracted %d findings at confidence %.2f "
            "(tiers: %s)"
            % (
                len(all_findings),
                overall_confidence,
                ", ".join(sorted({f.extraction_tier for f in all_findings})) or "none",
            )
        )

        return AgentResult(
            agent="vision",
            model=entry.model,
            payload=payload,
            attempts=[attempt_rec],
            final_confidence=overall_confidence,
            needs_human_review=needs_review,
            escalation_reason=escalation_reason,
            error=None,
        )

    # -------------------------------------------------------------------------
    # Targeted retry (attempt 2 and 3)
    # -------------------------------------------------------------------------

    async def _attempt_targeted_retry(
        self,
        inv: AgentInvocation,
        entry,
        client,
        source_rel: str,
        file_paths: list[str],
        t_start: float,
    ) -> AgentResult:
        """Targeted retry: crop the lowest-confidence finding and re-run VLM only."""
        settings = self.ctx.settings
        workspace = settings.workspace
        file_path = workspace / source_rel

        # -- Recover prior findings from the orchestrator relay ---------------
        prior_findings = self._extract_prior_findings(inv)

        if not prior_findings:
            # No prior findings to retry from — fall back to full cascade attempt
            return await self._attempt_full_cascade(
                inv, entry, client, source_rel, file_paths, t_start
            )

        # -- Find the lowest-confidence finding (deterministic: stable sort) --
        # Sort by confidence ascending, then by id for deterministic tie-breaking
        sorted_findings = sorted(prior_findings, key=lambda f: (f.confidence, f.id))
        target_finding = sorted_findings[0]

        # -- Verify the source file matches -----------------------------------
        # The retry must target the actual source file of the failed finding
        retry_source = target_finding.source_file
        retry_file_path = workspace / retry_source

        if not retry_file_path.exists():
            # Fall back to the invocation's own source_rel
            retry_file_path = file_path
            retry_source = source_rel

        # -- Get the page image -----------------------------------------------
        page_image = await self._get_page_image(
            retry_file_path, target_finding.page, settings
        )
        if page_image is None:
            # Cannot get page image; just return prior findings as-is
            avg = mean_confidence(prior_findings)
            page_leg = avg
            overall = (avg + page_leg) / 2.0
            duration_ms = round((time.perf_counter() - t_start) * 1000, 1)
            vision_out = VisionOutput(
                findings=prior_findings,
                page_legibility=page_leg,
                overall_confidence=overall,
                raw_text=format_findings_text(prior_findings),
                injection_flags=[],
            )
            payload = vision_out.model_dump()
            payload["_file_paths"] = file_paths
            payload["_summary"] = (
                "vision retry: could not get page image, returning prior findings"
            )
            return AgentResult(
                agent="vision",
                model=entry.model,
                payload=payload,
                attempts=[Attempt(n=inv.attempt, confidence=overall,
                                  failure_reason="retry: could not get page image",
                                  feedback_injected=inv.feedback,
                                  duration_ms=duration_ms)],
                final_confidence=overall,
                needs_human_review=overall < _THRESHOLD,
                escalation_reason=(
                    "could not get page image for retry" if overall < _THRESHOLD else None
                ),
            )

        # -- Crop to the low-confidence bbox ----------------------------------
        try:
            if target_finding.bbox is not None:
                cropped = crop_to_bbox(page_image, target_finding.bbox, pad=12)
            else:
                cropped = page_image  # no bbox: use full page image

            # Apply CLAHE + deskew contrast enhancement on retry
            enhanced = preprocess(cropped, clahe=True, deskew=False)
        except (ToolError, Exception):
            # If preprocessing fails, use the uncropped page image
            enhanced = page_image

        # -- Build targeted retry prompt --------------------------------------
        failure_context = inv.feedback or (
            "confidence %.2f below threshold %.2f" % (target_finding.confidence, _THRESHOLD)
        )
        retry_prompt = _RETRY_PROMPT_TEMPLATE.format(
            page=target_finding.page,
            failure=failure_context,
        )

        # -- Run VLM on the cropped, enhanced region only --------------------
        try:
            retry_findings = await self._run_vlm_on_pages(
                client, entry, [enhanced], retry_source,
                prompt=retry_prompt,
                page_override=target_finding.page,
            )
        except (OllamaError, Exception) as exc:
            # VLM failed on retry: preserve prior findings
            avg = mean_confidence(prior_findings)
            overall = (avg + avg) / 2.0
            duration_ms = round((time.perf_counter() - t_start) * 1000, 1)
            vision_out = VisionOutput(
                findings=prior_findings,
                page_legibility=avg,
                overall_confidence=overall,
                raw_text=format_findings_text(prior_findings),
                injection_flags=[],
            )
            payload = vision_out.model_dump()
            payload["_file_paths"] = file_paths
            payload["_summary"] = "vision retry: VLM failed, returning prior findings"
            return AgentResult(
                agent="vision",
                model=entry.model,
                payload=payload,
                attempts=[Attempt(n=inv.attempt, confidence=overall,
                                  failure_reason="retry VLM failed: %s" % exc,
                                  feedback_injected=inv.feedback,
                                  duration_ms=duration_ms)],
                final_confidence=overall,
                needs_human_review=overall < _THRESHOLD,
                escalation_reason=(
                    "retry VLM failed" if overall < _THRESHOLD else None
                ),
            )

        # -- Merge: replace only the targeted finding if retry is better ------
        merged_findings = self._merge_retry(
            prior_findings=prior_findings,
            target_finding=target_finding,
            retry_findings=retry_findings,
        )

        # -- Recompute confidence signals -------------------------------------
        avg_conf = mean_confidence(merged_findings) if merged_findings else 0.0
        page_legibility = avg_conf
        overall_confidence = (avg_conf + page_legibility) / 2.0
        overall_confidence = max(0.0, min(1.0, overall_confidence))

        failure_reason: Optional[str] = None
        if overall_confidence < _THRESHOLD:
            failure_reason = (
                "after retry, overall confidence %.2f still below threshold %.2f"
                % (overall_confidence, _THRESHOLD)
            )

        vision_out = VisionOutput(
            findings=merged_findings,
            page_legibility=page_legibility,
            overall_confidence=overall_confidence,
            raw_text=format_findings_text(merged_findings),
            injection_flags=[],
        )
        duration_ms = round((time.perf_counter() - t_start) * 1000, 1)
        payload = vision_out.model_dump()
        payload["_file_paths"] = file_paths
        payload["_summary"] = (
            "vision retry %d: %d findings at confidence %.2f"
            % (inv.attempt, len(merged_findings), overall_confidence)
        )

        return AgentResult(
            agent="vision",
            model=entry.model,
            payload=payload,
            attempts=[Attempt(
                n=inv.attempt,
                confidence=overall_confidence,
                failure_reason=failure_reason,
                feedback_injected=inv.feedback,
                duration_ms=duration_ms,
            )],
            final_confidence=overall_confidence,
            needs_human_review=overall_confidence < _THRESHOLD,
            escalation_reason=(
                "confidence %.2f below threshold after %d attempts"
                % (overall_confidence, inv.attempt)
                if overall_confidence < _THRESHOLD and inv.attempt >= MAX_ATTEMPTS["vision"]
                else None
            ),
        )

    # -------------------------------------------------------------------------
    # VLM helpers
    # -------------------------------------------------------------------------

    async def _run_vlm_on_pages(
        self,
        client,
        entry,
        page_images: list[Path],
        source_rel: str,
        prompt: str,
        page_override: Optional[int] = None,
    ) -> list[Finding]:
        """Send page images to the VLM with structured output schema.

        Uses VisionOutput.model_json_schema() as the format_schema so the
        client guarantees schema-valid JSON.  Never parses free-form prose.
        """
        findings: list[Finding] = []

        for img_idx, img_path in enumerate(page_images):
            page_num = page_override if page_override is not None else (img_idx + 1)

            # Always use structured output via VisionOutput schema
            schema = VisionOutput.model_json_schema()

            try:
                response = await client.chat_vision(
                    model=entry.model,
                    prompt=prompt,
                    image_paths=[img_path],
                    options=_VLM_OPTIONS,
                    keep_alive=entry.keep_alive,
                    format_schema=schema,
                )
            except OllamaError:
                raise

            raw_content = (response.get("message") or {}).get("content", "")
            page_findings = self._parse_vlm_response(
                raw_content, source_rel, page_num
            )
            findings.extend(page_findings)

        return findings

    def _parse_vlm_response(
        self,
        content: str,
        source_rel: str,
        page_num: int,
    ) -> list[Finding]:
        """Parse the structured VLM response into Finding objects.

        The VLM is asked to return a VisionOutput-shaped JSON via format_schema.
        If parsing fails (malformed output), return an empty list rather than
        fabricating findings.
        """
        if not content or not content.strip():
            return []

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # Malformed JSON: do not regex-repair, do not fabricate
            return []

        # data should conform to VisionOutput schema
        try:
            vo = VisionOutput.model_validate(data)
            # Re-stamp each finding with the correct page and source_file,
            # since the VLM may not know the actual page number.
            result: list[Finding] = []
            for f in vo.findings:
                # Validate bbox
                bbox = f.bbox
                if bbox is not None:
                    try:
                        # Ensure [x0, y0, x1, y1] with x0<x1, y0<y1
                        if len(bbox) == 4 and bbox[0] < bbox[2] and bbox[1] < bbox[3]:
                            pass  # valid
                        else:
                            bbox = None
                    except (TypeError, IndexError):
                        bbox = None

                result.append(
                    Finding(
                        id="v3_" + secrets.token_hex(4),
                        text=f.text,
                        page=page_num,  # authoritative page from caller
                        bbox=bbox,
                        confidence=max(0.0, min(1.0, f.confidence)),
                        source_file=source_rel,  # authoritative source from caller
                        extraction_tier=_VLM_TIER,  # always "vlm" for VLM output
                    )
                )
            return result
        except Exception:
            # Validation failed: do not fabricate
            return []

    # -------------------------------------------------------------------------
    # Retry helpers
    # -------------------------------------------------------------------------

    def _extract_prior_findings(self, inv: AgentInvocation) -> list[Finding]:
        """Extract findings from the most recent vision observation in prior."""
        prior = inv.inputs.get("prior") or []
        for obs in reversed(prior):
            if obs.get("target") == "vision":
                payload = obs.get("payload") or {}
                raw_findings = payload.get("findings") or []
                if raw_findings:
                    result = []
                    for rf in raw_findings:
                        try:
                            result.append(Finding.model_validate(rf))
                        except Exception:
                            pass
                    if result:
                        return result
        return []

    def _merge_retry(
        self,
        prior_findings: list[Finding],
        target_finding: Finding,
        retry_findings: list[Finding],
    ) -> list[Finding]:
        """Replace the targeted finding with the best retry result.

        Rules:
        1. If retry produced findings, take the highest-confidence one as C'.
        2. If C' confidence > target's confidence, replace target with C'.
        3. If C' confidence <= target's confidence, keep target (never regress).
        4. All other findings (A, B, D, E) are preserved unchanged.
        """
        if not retry_findings:
            # Retry produced nothing: keep all prior findings unchanged
            return list(prior_findings)

        # Take the best result from the retry
        best_retry = max(retry_findings, key=lambda f: f.confidence)

        merged: list[Finding] = []
        replaced = False
        for f in prior_findings:
            if f.id == target_finding.id and not replaced:
                if best_retry.confidence > target_finding.confidence:
                    # Retry improved: use the new finding
                    merged.append(
                        Finding(
                            id=best_retry.id,
                            text=best_retry.text,
                            page=target_finding.page,  # preserve original page
                            bbox=target_finding.bbox,  # preserve original page-space bbox
                            confidence=best_retry.confidence,
                            source_file=target_finding.source_file,
                            extraction_tier=_VLM_TIER,
                        )
                    )
                else:
                    # Retry was worse or equal: keep the original
                    merged.append(f)
                replaced = True
            else:
                merged.append(f)
        return merged

    async def _get_page_image(
        self,
        file_path: Path,
        page_num: int,
        settings,
    ) -> Optional[Path]:
        """Get (or rasterize) a specific page from a PDF or return the image path.

        For PDFs: rasterizes the specific page to a temp dir.
        For images: returns the file_path directly.
        Returns None if the file cannot be processed.
        """
        from ..tools.ocr import rasterize
        from ..tools.base import ToolError

        suffix = file_path.suffix.lower().lstrip(".")

        if suffix in ("pdf",):
            try:
                with tempfile.TemporaryDirectory(prefix="setu_retry_") as tmp:
                    page_images = rasterize(file_path, Path(tmp), dpi=300)
                    idx = page_num - 1
                    if 0 <= idx < len(page_images):
                        # Copy to a persistent temp location so it survives the context manager
                        import shutil
                        dest = Path(tempfile.mkdtemp(prefix="setu_page_")) / page_images[idx].name
                        shutil.copy2(str(page_images[idx]), str(dest))
                        return dest
            except (ToolError, Exception):
                return None
            return None
        elif suffix in VISION_EXTS:
            return file_path if file_path.exists() else None
        return None
