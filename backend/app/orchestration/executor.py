"""
execute_plan() - THE LOOP.  OWNER: P1.

This is the component that makes SETU an agent rather than a pipeline, and it is
the component most likely to be built wrong.  The wrong version hardcodes
`vision -> build_prompt -> reasoning`; it is forty minutes faster and it kills R6.

NOTHING IN THIS FILE KNOWS ABOUT THE FLAGSHIP.  It knows about steps, attempts,
approvals, observations and limits.  The flagship is a Scenario fixture consumed
by MockPlanner; a model-driven planner drops into the same three method calls.

Properties this loop guarantees, each covered by a test in
backend/tests/test_orchestrator.py:

  * plan approval before ANY step runs
  * rejection stops execution with no steps run and no artifact
  * a revised step outside the approved scope requires a fresh approval
  * a write shows its actual content before it is committed
  * a duplicate approval cannot run the same task twice
  * low confidence retries with structured feedback attached
  * exhausted attempts -> needs_human_review, never a quiet success
  * the iteration cap ends the task as needs_human_review, NOT completed
  * a tool exception becomes an observation and a visible `error` event
  * every attempt is audited
  * cancellation cleans up the in-flight run
"""

from __future__ import annotations

import asyncio
from typing import Optional

from ..config import MAX_ITERATIONS, ModelRegistry, Settings
from ..contracts import (
    ErrorCode,
    Observation,
    Plan,
    PlanStep,
    RouterDecision,
    StructuredError,
    TaskResult,
)
from ..security.audit import AuditLog
from ..tools.base import ToolContext
from . import policy
from .approvals import ApprovalGate, ApprovalRejected, in_scope, plan_request, scope_of, write_request
from .dispatcher import Dispatcher
from .events import EventBus
from .planner import Planner
from .state import TaskRecord


class Executor:
    def __init__(
        self,
        settings: Settings,
        models: ModelRegistry,
        dispatcher: Dispatcher,
        bus: EventBus,
        audit: AuditLog,
    ) -> None:
        self.settings = settings
        self.models = models
        self.dispatcher = dispatcher
        self.bus = bus
        self.audit = audit

    # -- emission helpers ----------------------------------------------------

    async def _emit(self, record: TaskRecord, type_: str, data: dict) -> None:
        await self.bus.emit(record.task_id, type_, data)  # type: ignore[arg-type]

    async def _audit(self, record: TaskRecord, **kwargs) -> None:
        entry = await self.audit.append(
            task_id=record.task_id,
            session=record.envelope.session_id,
            user=record.envelope.user,
            **kwargs,
        )
        await self._emit(record, "audit", entry.model_dump())

    async def _state(self, record: TaskRecord, state: str) -> None:
        record.set_state(state)  # type: ignore[arg-type]
        await self._emit(record, "state", {"state": state, "task_id": record.task_id})

    # -- the loop ------------------------------------------------------------

    async def execute_plan(
        self, record: TaskRecord, decision: RouterDecision, planner: Planner
    ) -> TaskResult:
        gate = ApprovalGate(record)
        ctx = ToolContext(
            settings=self.settings,
            task_id=record.task_id,
            session_id=record.envelope.session_id,
            mock=self.settings.mock_mode,
        )
        # Create this task's root eagerly, before any step runs. A plan whose
        # first action is list_dir(".") must see an empty directory rather than
        # fail on one that no write has created yet.
        ctx.ensure_root()

        try:
            # -- plan ---------------------------------------------------------
            await self._state(record, "planning")
            plan = await planner.propose(record.envelope, decision)
            record.plan = plan
            await self._emit(record, "plan", plan.model_dump())
            await self._audit(
                record, action="plan.proposed", result="%d steps" % len(plan.steps),
                args=[s.model_dump() for s in plan.steps],
            )

            # -- gate 1: approval BEFORE execution ----------------------------
            approved = await self._request_approval(record, gate, plan_request(record, plan))
            if not approved:
                raise ApprovalRejected("plan rejected by operator")
            plan.approved = True
            plan.approved_scope = scope_of(plan.steps)

            # -- iterate ------------------------------------------------------
            await self._state(record, "running")
            observations: list[Observation] = record.observations

            for iteration in range(1, MAX_ITERATIONS + 1):
                step = await planner.next_step(plan, observations)
                if step is None:
                    break

                # A revision outside the approved scope needs a fresh decision.
                if not in_scope(step, plan):
                    request = plan_request(
                        record,
                        Plan(steps=[step], approved=False, revisions=plan.revisions),
                        revision=True,
                    )
                    request.summary = (
                        "The plan changed based on what came back. New action outside "
                        "the approved scope: %s:%s - %s" % (step.kind, step.target, step.why)
                    )
                    ok = await self._request_approval(record, gate, request)
                    if not ok:
                        raise ApprovalRejected("revised step rejected by operator")
                    plan.approved_scope.append(step.scope_key())
                    await self._state(record, "running")

                record.iterations_used = iteration
                await self._emit(
                    record, "step_start",
                    {"step": step.model_dump(), "iteration": iteration,
                     "max_iterations": MAX_ITERATIONS},
                )

                observation = await self._run_step(record, gate, ctx, step, iteration)
                observations.append(observation)

                await self._emit(
                    record, "step_done",
                    {"step_n": step.n, "target": step.target, "ok": observation.ok,
                     "confidence": observation.confidence, "summary": observation.summary,
                     "simulated": observation.simulated, "iteration": iteration},
                )

                for ref in ctx.artifacts:
                    if ref.artifact_id not in {a.artifact_id for a in record.artifacts}:
                        record.artifacts.append(ref)
                        await self._emit(record, "artifact", ref.model_dump())

                if record.escalation_reason:
                    return await self._finalise(record, "needs_human_review",
                                                record.escalation_reason)

                if planner.is_satisfied(plan, observations):
                    break
            else:
                # The for-loop ran to exhaustion: the cap was hit.
                if not planner.is_satisfied(plan, observations):
                    message = policy.cap_message(record.iterations_used)
                    record.escalation_reason = message
                    await self._emit(record, "escalate",
                                     {"reason": message, "code": ErrorCode.ITERATION_CAP})
                    return await self._finalise(record, "needs_human_review", message)

            return await self._finalise(record, "completed", "plan satisfied")

        except ApprovalRejected as exc:
            await self._audit(record, action="approval.rejected", result=str(exc))
            return await self._finalise(record, "rejected", str(exc))
        except asyncio.CancelledError:
            await self._audit(record, action="task.cancelled", result="cancelled")
            record.set_state("cancelled")
            await self._emit(record, "state", {"state": "cancelled", "task_id": record.task_id})
            await self._emit(record, "done", {"state": "cancelled"})
            raise
        except Exception as exc:
            error = StructuredError(
                code=ErrorCode.INTERNAL, message="%s: %s" % (type(exc).__name__, exc)
            )
            record.error = error
            await self._emit(record, "error", error.model_dump())
            await self._audit(record, action="task.failed", result=error.message)
            return await self._finalise(record, "failed", error.message)

    # -- one step, with attempts --------------------------------------------

    async def _run_step(
        self,
        record: TaskRecord,
        gate: ApprovalGate,
        ctx: ToolContext,
        step: PlanStep,
        iteration: int,
    ) -> Observation:
        step.status = "running"

        if step.kind == "tool":
            _resolve_tool_placeholders(step, record.observations)
            spec = self.dispatcher.tools.get(step.target)
            if spec.requires_approval:
                preview, path = _write_preview(step)
                ok = await self._request_approval(
                    record, gate, write_request(record, step, preview, path)
                )
                if not ok:
                    raise ApprovalRejected("write to %s rejected by operator" % path)
                await self._state(record, "running")

            result = await self.dispatcher.run_tool(step, ctx)
            observation = self.dispatcher.observation_from_tool(step, result, iteration)
            step.status = "done" if result.ok else "failed"
            await self._audit(
                record, action="tool.%s" % step.target,
                result="ok" if result.ok else (result.error.code if result.error else "failed"),
                args=step.args, step=step.n, iteration=iteration,
            )
            if not result.ok and result.error is not None:
                # A tool exception is an observation the planner can react to,
                # AND a visible event.  It is never swallowed.
                await self._emit(record, "error",
                                 {"step_n": step.n, "target": step.target,
                                  **result.error.model_dump()})
            for chunk in (result.payload or {}).get("quarantined") or []:
                await self._emit(record, "quarantine", chunk)
            return observation

        # --- agent step, with the retry/confidence policy -------------------
        agent = step.target
        limit = policy.max_attempts_for(agent)
        feedback: Optional[str] = None
        inputs = _agent_inputs(record.observations, step, record.envelope.file_paths)
        result = None

        for attempt in range(1, limit + 1):
            result = await self.dispatcher.run_agent(step, iteration, attempt, feedback, inputs)
            attempt_row = policy.attempt_record(attempt, result, feedback)
            result.attempts = (result.attempts or [])[:-1] + [attempt_row]

            await self._emit(
                record, "attempt",
                {"step_n": step.n, "agent": agent, "attempt": attempt, "max_attempts": limit,
                 "confidence": attempt_row.confidence,
                 "failure_reason": attempt_row.failure_reason,
                 "feedback_injected": attempt_row.feedback_injected,
                 "simulated": result.simulated},
            )
            await self._audit(
                record, action="agent.%s" % agent,
                result="confidence=%.2f" % attempt_row.confidence,
                model=result.model, attempt=attempt, step=step.n, iteration=iteration,
                route_confidence=attempt_row.confidence, args=inputs,
            )

            decision = policy.evaluate(agent, result, attempt)
            if not decision.retry:
                if decision.escalate:
                    record.escalation_reason = decision.reason
                    result.needs_human_review = True
                    result.escalation_reason = decision.reason
                    await self._emit(record, "escalate",
                                     {"step_n": step.n, "agent": agent,
                                      "reason": decision.reason,
                                      "attempts": attempt, "max_attempts": limit})
                break
            feedback = decision.feedback

        assert result is not None
        step.status = "done" if not record.escalation_reason else "failed"
        return self.dispatcher.observation_from_agent(step, result, iteration)

    # -- approval plumbing ---------------------------------------------------

    async def _request_approval(self, record: TaskRecord, gate: ApprovalGate, request) -> bool:
        future = gate.open(request)
        await self._emit(record, "approval_request", request.model_dump())
        await self._emit(record, "state",
                         {"state": "awaiting_approval", "task_id": record.task_id})
        await self._audit(record, action="approval.requested", result=request.kind,
                          args=request.summary)
        # Parked here: no GPU held, event loop free.
        approved = await gate.wait(future)
        await self._emit(record, "approval_resolved",
                         {"approval_id": request.approval_id, "approved": approved,
                          "kind": request.kind})
        if approved:
            await self._audit(record, action="approval.granted", result=request.kind,
                              args=request.approval_id)
        return approved

    # -- finalisation --------------------------------------------------------

    async def _finalise(self, record: TaskRecord, state: str, summary: str) -> TaskResult:
        """Publish the terminal events BEFORE the terminal state becomes visible.

        Ordering here is load-bearing. `record.set_state()` is synchronous, but
        `self._audit()` below awaits `asyncio.to_thread` inside AuditLog.append,
        which is a real yield. Setting the state first meant a concurrent
        GET /api/tasks/{id} could see a terminal state while replay history
        still ended at "step_done" - so anything that reads history at that
        moment, or whose stream ends before the live "done" arrives, sees a task
        that finished with no `done` event. Measured on this machine before the
        change: 12 of 12 runs at natural timing observed the terminal state with
        "done" absent from history.

        `set_state` therefore happens LAST, after both terminal emits. Until
        then the record keeps its previous non-terminal state, which is the safe
        thing for a poller to see. Nothing between here and there reads
        `record.state`: TaskResult takes `state` as a parameter, and `_audit`
        and `_emit` only read task_id, envelope.session_id and envelope.user.

        The audit call is deliberately NOT moved after the emits instead:
        `_audit` emits its own "audit" event, so that ordering would push an
        "audit" event after "done" and break the same invariant a different way.
        """
        result = TaskResult(
            task_id=record.task_id,
            state=state,  # type: ignore[arg-type]
            summary=summary,
            observations=list(record.observations),
            artifacts=list(record.artifacts),
            needs_human_review=state == "needs_human_review",
            escalation_reason=record.escalation_reason,
            iterations_used=record.iterations_used,
            error=record.error,
            mock_mode=self.settings.mock_mode,
        )
        await self._audit(record, action="task.finalised", result=state, args=summary)
        await self._emit(record, "state", {"state": state, "task_id": record.task_id})
        await self._emit(record, "done", result.model_dump())
        # LAST. See the docstring: the terminal state must not become visible
        # to a concurrent reader before the events describing it are in history.
        record.set_state(state)  # type: ignore[arg-type]
        return result


def _resolve_tool_placeholders(step: PlanStep, observations: list[Observation]) -> None:
    """Resolve placeholder strings in tool step arguments from prior observations.

    When the planner schedules write_file early in a multi-step plan, it cannot know
    the real output of future reasoning/coding steps, so it often writes placeholder
    strings like '<generated_code>' or '<retrieved_document_content>'.
    This resolves such placeholders to the actual substantive text generated by
    the preceding steps.
    """
    if not step.args or not observations:
        return

    # Check if content is a placeholder
    content = step.args.get("content")
    if not isinstance(content, str):
        return

    stripped = content.strip()
    # Matches patterns like <generated_code>, <code_output>, <document_content>,
    # <extracted_text>, etc., or empty string.
    is_placeholder = (
        (stripped.startswith("<") and stripped.endswith(">"))
        or stripped in {"", "...", "TODO", "TBD"}
    )
    if not is_placeholder:
        return

    # Look backwards through observations for generated text or code
    for obs in reversed(observations):
        payload = obs.payload or {}
        # 1. Coding agent code output
        if payload.get("code"):
            step.args["content"] = str(payload["code"])
            return
        # 2. Reasoning agent drafted content
        if payload.get("content"):
            step.args["content"] = str(payload["content"])
            return
        # 3. Vision agent raw text or findings text
        if payload.get("raw_text"):
            step.args["content"] = str(payload["raw_text"])
            return


def _write_preview(step: PlanStep) -> tuple[str, str]:
    """The ACTUAL content a write step intends to commit, for Layer 4 review."""
    args = step.args or {}
    if step.target == "write_file":
        return str(args.get("content", "")), str(args.get("path", "<unknown>"))
    if step.target == "docgen":
        data = args.get("data") or {}
        body = str(data.get("body") or data.get("content") or "")
        title = str(data.get("title") or "")
        preview = (title + "\n\n" + body).strip() or "(no textual body in this document)"
        return preview, str(args.get("out_name") or (str(args.get("kind", "file")) + " artifact"))
    return "", str(args.get("path", "<unknown>"))


def _agent_inputs(
    observations: list[Observation],
    step: PlanStep,
    task_file_paths: Optional[list[str]] = None,
) -> dict:
    """What the orchestrator RELAYS into an agent call.

    This is the relay principle in code: an agent never reads another agent's
    output directly - the orchestrator hands it over as data.
    """
    return {
        "why": step.why,
        "args": step.args,
        "file_paths": task_file_paths or [],
        "prior": [
            {"target": o.target, "ok": o.ok, "summary": o.summary, "payload": o.payload}
            for o in observations[-3:]
        ],
    }
