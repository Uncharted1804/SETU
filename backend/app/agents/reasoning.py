"""
Reasoning agent.  OWNER: P3.

Job: drafting, summarising, approval notes, plan generation and - critically -
driving the tool loop.  Model: capability "planning" from config/models.yaml
(currently qwen3:8b).  Threshold 0.65, 3 attempts.

Confidence signal: TWO things - the model's self-reported score AND whether the
output is grounded in the retrieved knowledge base.  An ungrounded draft is not
a confident draft no matter what number the model emits.

THE VERIFIER.  After drafting, every substantive claim is checked against the
retrieved chunks.  Claims with no support land in `unsupported_claims` and
render yellow.  It satisfies R10's grounding intent, it is the honest answer to
"what if the model is wrong", and it is the mechanism that catches an injected
claim (security/injection.py defence 4).

What changes on retry: pull more or different KB context, or ask the model to
critique its own first draft before rewriting.

P3 TODO, in order (acceptance stated so it is checkable by someone else):
  1. `run()` real path: findings JSON + wrapped chunks + role prompt ->
     ReasoningOutput.  Acceptance: an approval note with >= 3 citations.
  2. Wrap every retrieved chunk with security.injection.wrap_untrusted and put
     SYSTEM_DATA_RULE in the system message.  Acceptance: no chunk text ever
     reaches the instruction region un-wrapped (assert it in a test).
  3. Verifier: rapidfuzz-match each sentence against retrieved chunk spans.
     Acceptance: the demo produces exactly one yellow unsupported claim.
  4. Retry path: use inv.feedback to widen retrieval, not to re-ask verbatim.
"""

from __future__ import annotations

from ..contracts import AgentInvocation, AgentResult, ErrorCode, StructuredError
from .base import AgentContext


class ReasoningAgent:
    name = "reasoning"

    def __init__(self, ctx: AgentContext) -> None:
        self.ctx = ctx

    async def run(self, inv: AgentInvocation) -> AgentResult:
        entry = self.ctx.registry.resolve("reasoning")
        client = self.ctx.client()
        await client.ensure_model(entry.model)
        # Unimplemented real components fail clearly. They never return
        # plausible-looking empty output that a demo could mistake for success.
        return AgentResult(
            agent="reasoning",
            model=entry.model,
            payload={},
            attempts=[],
            final_confidence=0.0,
            needs_human_review=True,
            escalation_reason="reasoning agent real path not implemented (owner: P3)",
            error=StructuredError(
                code=ErrorCode.NOT_IMPLEMENTED,
                message=(
                    "P3 owns agents/reasoning.py. Run with SETU_MOCK_MODE=1 to exercise "
                    "the orchestration path with deterministic fixtures."
                ),
                detail={"model": entry.model, "attempt": inv.attempt},
            ),
        )
