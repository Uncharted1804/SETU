"""
The single dispatcher.  OWNER: P1.

ONE function runs a step, and it does not care whether the step is an agent or a
tool.  That is why adding a fourth agent is a registry entry: nothing in the
executor branches on agent identity.

WHAT THE DISPATCHER GUARANTEES:

  * Only allowlisted targets run.  A step naming an unregistered tool or agent
    fails validation in PlanStep and, belt-and-braces, again here.
  * Tool arguments are parsed into their typed model before the handler is
    called.  A malformed model proposal never reaches a handler.
  * Tool EXCEPTIONS become structured observations, never unhandled 500s.  The
    loop continues so the planner can react to the failure - that is what makes
    a failed tool call a fact the agent can reason about rather than a crash.
  * Models can PROPOSE actions; only this module dispatches them.  Agents never
    invoke each other, and tools never invoke other registered tools.
"""

from __future__ import annotations

import time
from typing import Optional

from ..agents import AgentRegistry
from ..config import ModelRegistry, Settings
from ..contracts import (
    AgentInvocation,
    AgentResult,
    Observation,
    PlanStep,
    ToolResult,
)
from ..tools.base import ToolContext
from ..tools.registry import ToolRegistry, error_to_structured


class Dispatcher:
    def __init__(
        self,
        settings: Settings,
        models: ModelRegistry,
        agents: AgentRegistry,
        tools: ToolRegistry,
    ) -> None:
        self.settings = settings
        self.models = models
        self.agents = agents
        self.tools = tools

    # -- agents --------------------------------------------------------------

    async def run_agent(
        self,
        step: PlanStep,
        iteration: int,
        attempt: int,
        feedback: Optional[str],
        inputs: dict,
    ) -> AgentResult:
        entry = self.models.resolve_for_agent(step.target)
        agent = self.agents.get(step.target)
        inv = AgentInvocation(
            agent=step.target,  # type: ignore[arg-type]
            model_id=entry.id,
            model=entry.model,
            prompt_summary=step.why,
            inputs=inputs,
            attempt=attempt,
            feedback=feedback,
        )
        try:
            return await agent.run(inv)
        except Exception as exc:  # an agent that throws is still an observation
            return AgentResult(
                agent=step.target,  # type: ignore[arg-type]
                model=entry.model,
                payload={},
                attempts=[],
                final_confidence=0.0,
                needs_human_review=True,
                escalation_reason="agent raised %s" % type(exc).__name__,
                error=error_to_structured(exc, step.target),
            )

    # -- tools ---------------------------------------------------------------

    async def run_tool(self, step: PlanStep, ctx: ToolContext) -> ToolResult:
        started = time.perf_counter()
        before = len(ctx.artifacts)
        try:
            payload = await self.tools.call(step.target, step.args, ctx)
        except Exception as exc:
            return ToolResult(
                tool=step.target,  # type: ignore[arg-type]
                ok=False,
                payload={},
                error=error_to_structured(exc, step.target),
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
        return ToolResult(
            tool=step.target,  # type: ignore[arg-type]
            ok=True,
            payload=payload,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
            artifacts=ctx.artifacts[before:],
            simulated=bool(payload.get("simulated")),
        )

    # -- observation shaping -------------------------------------------------

    @staticmethod
    def observation_from_agent(
        step: PlanStep, result: AgentResult, iteration: int
    ) -> Observation:
        summary = result.payload.get("_summary") or (
            "%s produced output at confidence %.2f" % (step.target, result.final_confidence)
        )
        if result.error is not None:
            summary = "%s failed: %s" % (step.target, result.error.message)
        return Observation(
            step_n=step.n,
            kind="agent",
            target=step.target,
            ok=result.error is None,
            summary=summary,
            payload=result.payload,
            error=result.error,
            confidence=result.final_confidence,
            attempts=result.attempts,
            iteration=iteration,
            simulated=result.simulated,
        )

    @staticmethod
    def observation_from_tool(step: PlanStep, result: ToolResult, iteration: int) -> Observation:
        if not result.ok and result.error is not None:
            summary = "%s failed: %s" % (step.target, result.error.message)
        else:
            summary = result.payload.get("_summary") or ("%s returned a result" % step.target)
        return Observation(
            step_n=step.n,
            kind="tool",
            target=step.target,
            ok=result.ok,
            summary=summary,
            payload=result.payload,
            error=result.error,
            iteration=iteration,
            simulated=result.simulated,
        )
