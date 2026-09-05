"""
Vision agent.  OWNER: P2.

Job: extract text and findings from scans, photos, handwriting and engineering
drawings.  Model: resolved from config/models.yaml capability "vision"
(currently qwen3-vl:4b on this machine).

Confidence signal: TWO numbers, deliberately - the model's self-reported score
AND how much of the page was legible.  Threshold 0.70, 3 attempts.

What changes on retry: crop and zoom into the unclear region, raise contrast,
and ask specifically about the low-confidence part.  NOT a re-read of the whole
page.  See tools/ocr.py::crop_to_bbox.

SCOPE LIMIT carried from config/models.yaml: this agent EXTRACTS.  It never
interprets or approves an engineering drawing - that escalates to a human.

P2 TODO, in order (acceptance stated so P1 or P6 can check it):
  1. `run()` real path: PDF/image in -> VisionOutput with >= 5 findings on the
     demo scan, each carrying page, bbox, confidence and extraction_tier.
  2. Structured output: pass a JSON schema via client.chat_vision(
     format_schema=VisionOutput.model_json_schema()) rather than parsing prose.
  3. Retry path: on attempt 2, use inv.feedback plus the lowest-confidence
     finding's bbox to re-ask about that region only.  Acceptance: attempt 2
     measurably raises confidence on the deliberately blurry demo region.
"""

from __future__ import annotations

from ..contracts import AgentInvocation, AgentResult, ErrorCode, StructuredError
from .base import AgentContext


class VisionAgent:
    name = "vision"

    def __init__(self, ctx: AgentContext) -> None:
        self.ctx = ctx

    async def run(self, inv: AgentInvocation) -> AgentResult:
        entry = self.ctx.model_for("vision")
        client = self.ctx.client()
        await client.ensure_model(entry.model)
        # Deliberately not a silent stub: an unimplemented real component fails
        # clearly rather than returning plausible-looking empty output.
        return AgentResult(
            agent="vision",
            model=entry.model,
            payload={},
            attempts=[],
            final_confidence=0.0,
            needs_human_review=True,
            escalation_reason="vision agent real path not implemented (owner: P2)",
            error=StructuredError(
                code=ErrorCode.NOT_IMPLEMENTED,
                message=(
                    "P2 owns agents/vision.py. Run with SETU_MOCK_MODE=1 to exercise "
                    "the orchestration path with deterministic vision fixtures."
                ),
                detail={"model": entry.model, "attempt": inv.attempt},
            ),
        )
