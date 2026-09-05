"""
Layer 4 - the human-in-the-loop gate.  OWNER: P1.

Four properties, each of which is a separate failure if you skip it:

  1. PLAN APPROVAL BEFORE EXECUTION.  No step runs until a human approves.
  2. REJECTION STOPS EXECUTION.  Rejecting is terminal; the task ends `rejected`
     with no steps run and no artifact.
  3. SCOPE.  The approval records `approved_scope` - the set of "kind:target"
     keys the human saw.  If the planner later revises to a step OUTSIDE that
     set, execution pauses again for a fresh decision.  Approving "vision then
     kb_search" is not approval to run `write_file`.
  4. WRITES SHOW THE CONTENT.  A write approval carries the actual content (or a
     diff against what is on disk), not just a filename.  Approving a path is
     not review.

TWO THINGS THIS MUST NOT DO:

  * BLOCK THE EVENT LOOP.  Waiting is `await future` on an asyncio.Future that
    the API resolves.  No sleeping poll, no thread.
  * HOLD THE GPU.  The wait happens in the executor between steps, entirely
    outside llm/ollama_client.py's inference semaphore.  A human thinking for two
    minutes must not keep a model resident and every other task queued.

DUPLICATE APPROVALS.  Deciding an already-decided approval is rejected with a
conflict, and a task in a terminal state is never re-run.  Both are asserted in
backend/tests/test_orchestrator.py.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from ..contracts import ApprovalRequest, Plan, PlanStep
from .state import TaskRecord, new_approval_id


class ApprovalConflict(RuntimeError):
    """Raised when a decision arrives for an approval that is already resolved."""


class ApprovalRejected(RuntimeError):
    """Raised inside the executor when a human rejects.  Terminates the task."""

    def __init__(self, note: Optional[str] = None) -> None:
        self.note = note
        super().__init__(note or "rejected by operator")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def plan_request(record: TaskRecord, plan: Plan, revision: bool = False) -> ApprovalRequest:
    kinds = ", ".join("%s:%s" % (s.kind, s.target) for s in plan.steps)
    return ApprovalRequest(
        approval_id=new_approval_id(),
        task_id=record.task_id,
        kind="plan_revision" if revision else "plan",
        created_at=_now(),
        summary=("Revised plan - %d step(s): %s" if revision else "Plan - %d step(s): %s")
        % (len(plan.steps), kinds),
        steps=list(plan.steps),
    )


def write_request(record: TaskRecord, step: PlanStep, preview: str, path: str) -> ApprovalRequest:
    """A write approval that renders the ACTUAL content about to be committed."""
    return ApprovalRequest(
        approval_id=new_approval_id(),
        task_id=record.task_id,
        kind="write",
        created_at=_now(),
        summary="%s wants to write %s (%d characters)" % (step.target, path, len(preview or "")),
        steps=[step],
        preview=preview,
        target_path=path,
    )


def scope_of(steps: list[PlanStep]) -> list[str]:
    seen: list[str] = []
    for step in steps:
        key = step.scope_key()
        if key not in seen:
            seen.append(key)
    return seen


def in_scope(step: PlanStep, plan: Plan) -> bool:
    """A revised step is in scope only if the human already saw that kind:target."""
    return step.scope_key() in (plan.approved_scope or [])


class ApprovalGate:
    """Creates the request, parks the executor, and is resolved by the API."""

    def __init__(self, record: TaskRecord) -> None:
        self.record = record

    def open(self, request: ApprovalRequest) -> asyncio.Future:
        if self.record.pending_approval and not self.record.pending_approval.decided:
            raise ApprovalConflict(
                "task %s already has an undecided approval (%s)"
                % (self.record.task_id, self.record.pending_approval.approval_id)
            )
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self.record.pending_approval = request
        self.record.approval_future = future
        self.record.set_state("awaiting_approval")
        return future

    async def wait(self, future: asyncio.Future) -> bool:
        """Park here.  No GPU is held and the event loop stays free."""
        approved = await future
        return bool(approved)

    def resolve(self, approval_id: str, approved: bool) -> ApprovalRequest:
        """Called by the API.  Idempotency is a hard error, not a silent no-op."""
        pending = self.record.pending_approval
        if pending is None or pending.approval_id != approval_id:
            raise ApprovalConflict("no pending approval %r on task %s" % (approval_id, self.record.task_id))
        if pending.decided:
            raise ApprovalConflict("approval %s has already been decided" % approval_id)
        if self.record.is_terminal:
            raise ApprovalConflict(
                "task %s is already %s; a second approval cannot re-run it"
                % (self.record.task_id, self.record.state)
            )
        pending.decided = True
        future = self.record.approval_future
        if future is not None and not future.done():
            future.set_result(approved)
        self.record.approval_future = None
        self.record.touch()
        return pending
