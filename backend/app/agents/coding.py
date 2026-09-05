"""
Coding agent.  OWNER: P4.

Job: writes and debugs code; performs numerical analysis.  Model: capability
"code" from config/models.yaml (currently qwen2.5-coder:7b).

CONFIDENCE IS OBJECTIVE, NOT SELF-REPORTED: exit_code == 0 gives 1.0, anything
else gives 0.0.  Threshold is therefore 1.00, and CodingOutput enforces the
relationship in the contract itself.

Say this precisely to a judge: a zero exit code is evidence the code RAN, not
proof that arbitrary program logic is correct.  The claim we make is
"objectively verified execution", not "verified correctness".

WHY CODING GETS 4 ATTEMPTS while vision and reasoning get 3: its failure signal
is the most reliable in the system.  A traceback tells the model precisely what
to fix; a hazy confidence score does not.  Retries here have the highest
expected value, so they get the largest budget.  That asymmetry is a design
decision worth pointing out unprompted.

What changes on retry: the actual stderr and traceback are fed into the next
prompt (agents/base.py::build_feedback).

P4 TODO, in order:
  1. `run()` real path: prompt -> code -> tools.sandbox.run_in_sandbox ->
     CodingOutput.  Acceptance: run_python("print(2+2)") gives stdout "4".
  2. Retry path: attempt 2 receives the attempt-1 traceback verbatim.
     Acceptance: the demo script fails on attempt 1 and passes on attempt 2,
     and the UI shows "attempt 2/4 - feeding traceback".
  3. NEVER add a host-execution fallback.  If Docker is down, surface
     SANDBOX_UNAVAILABLE.
"""

from __future__ import annotations

from ..contracts import AgentInvocation, AgentResult, ErrorCode, StructuredError
from .base import AgentContext


class CodingAgent:
    name = "coding"

    def __init__(self, ctx: AgentContext) -> None:
        self.ctx = ctx

    async def run(self, inv: AgentInvocation) -> AgentResult:
        entry = self.ctx.registry.resolve("code")
        client = self.ctx.client()
        await client.ensure_model(entry.model)
        # Unimplemented real components fail clearly. They never return
        # plausible-looking empty output that a demo could mistake for success.
        return AgentResult(
            agent="coding",
            model=entry.model,
            payload={},
            attempts=[],
            final_confidence=0.0,
            needs_human_review=True,
            escalation_reason="coding agent real path not implemented (owner: P4)",
            error=StructuredError(
                code=ErrorCode.NOT_IMPLEMENTED,
                message=(
                    "P4 owns agents/coding.py. Run with SETU_MOCK_MODE=1 to exercise "
                    "the orchestration path with deterministic fixtures."
                ),
                detail={"model": entry.model, "attempt": inv.attempt},
            ),
        )
